"""The generated OpenAPI schema is the contract handed to the desktop client."""

from server import app


def test_schema_is_openapi_3():
    assert app.openapi()["openapi"].startswith("3.")


def test_schema_documents_every_rest_endpoint():
    paths = app.openapi()["paths"]

    assert sorted(paths["/machines"]) == ["get", "post"]
    assert sorted(paths["/machines/{machine_id}"]) == ["delete", "get"]
    assert sorted(paths["/machines/packages"]) == ["post"]


def test_package_mutation_action_is_constrained_to_add_and_remove():
    action = app.openapi()["components"]["schemas"]["PackageMutationRequest"]["properties"][
        "action"
    ]

    assert action["enum"] == ["add", "remove"]


def test_machine_ids_is_optional_so_a_fleet_wide_change_can_omit_it():
    request_schema = app.openapi()["components"]["schemas"]["PackageMutationRequest"]

    assert "machine_ids" not in request_schema["required"]


def test_delivery_outcomes_are_enumerated_for_the_client():
    delivery = app.openapi()["components"]["schemas"]["PackageMutationResultItem"]["properties"][
        "delivery"
    ]

    assert delivery["enum"] == ["pushed", "queued", "unchanged"]
    assert delivery["description"]


def test_the_agent_websocket_protocol_is_documented_in_the_api_description():
    description = app.openapi()["info"]["description"]

    assert "/ws/machines/{machine_id}" in description
    for message_type in ("telemetry", "config_report", "apply_result", "apply_config"):
        assert message_type in description
