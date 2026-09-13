from .base import Domain, Entity, StateTransition, Invariant, ToolResult, now_iso


class DevOpsDomain(Domain):
    name = "devops"
    schema_version = "1.0"

    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        self.entities = {
            "ISS-100": Entity("ISS-100", "open", data={"blocking": False, "linked_pr": None}),
            "ISS-101": Entity("ISS-101", "in_review", data={"blocking": False, "linked_pr": "PR-101"}),
            "ISS-102": Entity("ISS-102", "open", data={"blocking": True, "linked_pr": None}),
            "ISS-103": Entity("ISS-103", "merged", data={"blocking": False, "linked_pr": "PR-103"}),
            "ISS-104": Entity("ISS-104", "closed", data={"blocking": False, "linked_pr": "PR-104"}),
            "DEP-100": Entity("DEP-100", "staging", data={"release": "REL-100", "environment": "staging"}),
            "DEP-101": Entity("DEP-101", "deployed", data={"release": "REL-101", "environment": "prod"}),
            "REL-100": Entity("REL-100", "ready", data={"production_deployed": False}),
        }
        self.transitions = [
            StateTransition("open", "in_progress", "start", ["issue is open"], ["issue is in_progress"], 600),
            StateTransition("in_progress", "in_review", "review", ["work completed"], ["issue is in_review"], 600),
            StateTransition("in_review", "merged", "merge", ["review approved"], ["issue is merged"], 600),
            StateTransition("merged", "deployed", "deploy", ["release merged"], ["release deployed"], 600),
            StateTransition("staging", "deployed", "deploy", ["staging complete"], ["deployment is deployed"], 600),
            StateTransition("deployed", "closed", "close", ["deployment complete"], ["deployment is closed"], 600),
            StateTransition("closed", "open", "reopen", ["authorized user"], ["issue is open"], 600),
        ]
        self.invariants = [
            Invariant("no_blocking_issue_before_prod",
                      lambda c: (not c.get("blocking_issue", False),
                                  "Production deployment is blocked by an open blocking issue."),
                      "domain_fact"),
            Invariant("staging_before_prod",
                      lambda c: (c.get("staging_complete", True),
                                  "Production deployment must follow staging."),
                      "workflow_rule"),
        ]

    def simulate_tool_call(self, action, payload):
        ts = now_iso()
        iid = payload.get("issue_id", "ISS-100")
        issue = self.entities.get(iid)
        if action == "get_issue":
            if not issue:
                return ToolResult(False, action, iid, {"error": "issue_not_found"}, timestamp=ts)
            return ToolResult(True, action, iid, {"issue_id": iid, "state": issue.state,
                                                  "blocking": issue.data.get("blocking", False),
                                                  "linked_pr": issue.data.get("linked_pr"),
                                                  "as_of_timestamp": issue.updated_at}, timestamp=ts)
        if action == "start":
            if not issue:
                return ToolResult(False, action, iid, {"error": "issue_not_found"}, timestamp=ts)
            if issue.state != "open":
                return ToolResult(False, action, iid, {"error": "illegal_state", "state": issue.state}, timestamp=ts)
            issue.state = "in_progress"; issue.updated_at = ts
            return ToolResult(True, action, iid, {"issue_id": iid, "state": issue.state, "as_of_timestamp": ts}, timestamp=ts)
        if action == "review":
            if not issue:
                return ToolResult(False, action, iid, {"error": "issue_not_found"}, timestamp=ts)
            if issue.state != "in_progress":
                return ToolResult(False, action, iid, {"error": "illegal_state", "state": issue.state}, timestamp=ts)
            issue.state = "in_review"; issue.updated_at = ts
            return ToolResult(True, action, iid, {"issue_id": iid, "state": issue.state, "as_of_timestamp": ts}, timestamp=ts)
        if action == "merge":
            if not issue:
                return ToolResult(False, action, iid, {"error": "issue_not_found"}, timestamp=ts)
            if issue.state != "in_review":
                return ToolResult(False, action, iid, {"error": "illegal_state", "state": issue.state}, timestamp=ts)
            issue.state = "merged"; issue.updated_at = ts
            return ToolResult(True, action, iid, {"issue_id": iid, "state": issue.state, "as_of_timestamp": ts}, timestamp=ts)
        if action == "deploy":
            env = payload.get("environment", "staging")
            dep_id = payload.get("deployment_id", "DEP-100")
            dep = self.entities.get(dep_id)
            if not dep:
                return ToolResult(False, action, dep_id, {"error": "deployment_not_found"}, timestamp=ts)
            blocking = bool(payload.get("blocking_issue", False)) or any(
                x.data.get("blocking") and x.state not in {"closed", "deployed"}
                for x in self.entities.values() if x.id.startswith("ISS-"))
            staging_complete = bool(payload.get("staging_complete", dep.state == "staging"))
            if env == "prod" and blocking:
                return ToolResult(False, action, dep_id, {"error": "blocking_issue"}, timestamp=ts)
            if env == "prod" and not staging_complete:
                return ToolResult(False, action, dep_id, {"error": "staging_required", "state": dep.state}, timestamp=ts)
            if env == "prod":
                dep.state = "deployed"; dep.data["environment"] = "prod"; dep.updated_at = ts
            return ToolResult(True, action, dep_id, {"deployment_id": dep_id, "environment": env,
                                                      "state": dep.state, "as_of_timestamp": ts}, timestamp=ts)
        if action == "close_issue":
            if not issue:
                return ToolResult(False, action, iid, {"error": "issue_not_found"}, timestamp=ts)
            if issue.state == "closed":
                return ToolResult(False, action, iid, {"error": "illegal_state", "state": issue.state}, timestamp=ts)
            if not issue.data.get("linked_pr"):
                return ToolResult(False, action, iid, {"error": "missing_linked_pr"}, timestamp=ts)
            issue.state = "closed"; issue.updated_at = ts
            return ToolResult(True, action, iid, {"issue_id": iid, "state": issue.state,
                                                  "linked_pr": issue.data.get("linked_pr"), "as_of_timestamp": ts}, timestamp=ts)
        if action == "close":
            return self.simulate_tool_call("close_issue", payload)
        if action == "reopen":
            if not issue:
                return ToolResult(False, action, iid, {"error": "issue_not_found"}, timestamp=ts)
            if issue.state != "closed":
                return ToolResult(False, action, iid, {"error": "illegal_state", "state": issue.state}, timestamp=ts)
            issue.state = "open"; issue.updated_at = ts
            return ToolResult(True, action, iid, {"issue_id": iid, "state": issue.state, "as_of_timestamp": ts}, timestamp=ts)
        return ToolResult(False, action, iid, {"error": "unknown_action"}, timestamp=ts)
