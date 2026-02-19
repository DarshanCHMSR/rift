"""Unit tests for SupervisorAgent — StateGraph wiring and validation."""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.supervisor import SupervisorAgent, PipelineState


def test_supervisor_graph_compiles():
    """The StateGraph should compile without errors."""
    agent = SupervisorAgent()
    assert agent.app is not None


def test_supervisor_has_all_nodes():
    """Every expected node must be present in the compiled graph."""
    agent = SupervisorAgent()
    # langgraph compiled graph exposes node names
    graph_nodes = set(agent.app.get_graph().nodes.keys())
    expected = {
        "init", "clone", "test", "parse_errors",
        "generate_fixes", "commit", "push", "sandbox",
        "score", "cleanup",
    }
    missing = expected - graph_nodes
    assert not missing, f"Missing nodes: {missing}"


def test_route_after_test_passed():
    """If exit code is 0, routing goes to push."""
    agent = SupervisorAgent()
    state = {"test_exit_code": 0, "attempt": 1, "retry_limit": 5, "start_time": 0, "repo_path": "/tmp"}
    assert agent._route_after_test(state) == "push"


def test_route_after_test_failed_with_retries():
    """If tests fail and retries remain, routing goes to parse_errors."""
    import time
    agent = SupervisorAgent()
    state = {"test_exit_code": 1, "attempt": 1, "retry_limit": 5, "start_time": time.time(), "repo_path": "/tmp"}
    assert agent._route_after_test(state) == "parse_errors"


def test_route_after_test_exhausted():
    """If retries exhausted, routing goes to push."""
    import time
    agent = SupervisorAgent()
    state = {"test_exit_code": 1, "attempt": 5, "retry_limit": 5, "start_time": time.time(), "repo_path": "/tmp"}
    assert agent._route_after_test(state) == "push"


def test_route_after_parse_no_issues():
    """If no issues found, skip to push."""
    assert SupervisorAgent._route_after_parse({"current_issues": []}) == "push"


def test_route_after_parse_with_issues():
    """If issues found, go to generate_fixes."""
    assert SupervisorAgent._route_after_parse({"current_issues": [{"file": "x"}]}) == "generate_fixes"


def test_route_after_fix_no_fixes():
    """If no fixes generated, skip to push."""
    assert SupervisorAgent._route_after_fix({"current_fixes": []}) == "push"


def test_route_after_fix_with_fixes():
    """If fixes applied, go to commit."""
    assert SupervisorAgent._route_after_fix({"current_fixes": [{"summary": "x"}]}) == "commit"


def test_route_after_commit_retry():
    """After commit, if retries remain, loop back to test."""
    import time
    agent = SupervisorAgent()
    state = {"attempt": 1, "retry_limit": 5, "start_time": time.time()}
    assert agent._route_after_commit(state) == "test"


def test_route_after_commit_exhausted():
    """After commit, if retries exhausted, go to push."""
    import time
    agent = SupervisorAgent()
    state = {"attempt": 5, "retry_limit": 5, "start_time": time.time()}
    assert agent._route_after_commit(state) == "push"


def test_validate_pipeline_execution():
    """Validation should detect missing required nodes."""
    state = {
        "nodes_executed": ["init", "clone", "test", "push", "score", "cleanup"],
        "container_ids": ["abc123"],
        "branch_name": "TEST_AI_Fix",
        "push_message": "Push successful",
        "sandbox_verification": {"passed": True},
        "errors_encountered": [],
        "attempt": 1,
    }
    result = SupervisorAgent.validate_pipeline_execution(state)
    assert result["all_required_nodes_executed"] is True
    assert result["docker_containers_used"] == 1
    assert result["branch_created"] is True
    assert result["push_attempted"] is True


def test_validate_detects_missing_nodes():
    """Validation should flag missing required nodes."""
    state = {
        "nodes_executed": ["init", "clone"],
        "container_ids": [],
        "branch_name": "",
        "push_message": "",
        "sandbox_verification": {},
        "errors_encountered": [],
        "attempt": 0,
    }
    result = SupervisorAgent.validate_pipeline_execution(state)
    assert result["all_required_nodes_executed"] is False
    assert len(result["missing_nodes"]) > 0


def test_build_branch_name():
    """Branch name should be uppercase with _AI_Fix suffix."""
    name = SupervisorAgent._build_branch_name("Alpha Team", "Bob Smith")
    assert name.endswith("_AI_Fix")
    assert name == "ALPHA_TEAM_BOB_SMITH_AI_Fix"


def test_build_branch_name_special_chars():
    """Special characters should be stripped."""
    name = SupervisorAgent._build_branch_name("tëam-1!", "léader@2")
    assert name.endswith("_AI_Fix")
    assert "!" not in name
    assert "@" not in name
