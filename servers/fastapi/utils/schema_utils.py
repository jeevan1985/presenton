from copy import deepcopy
from typing import Any, List

from openai import NOT_GIVEN

from utils.dict_utils import (
    get_dict_paths_with_key,
    get_dict_at_path,
    has_more_than_n_keys,
)

supported_string_formats = [
    "date-time",
    "time",
    "date",
    "duration",
    "email",
    "hostname",
    "ipv4",
    "ipv6",
    "uuid",
]


def remove_fields_from_schema(schema: dict, fields_to_remove: List[str]):
    schema = deepcopy(schema)
    properties_paths = get_dict_paths_with_key(schema, "properties")
    for path in properties_paths:
        parent_obj = get_dict_at_path(schema, path)
        if "properties" in parent_obj and isinstance(parent_obj["properties"], dict):
            for field in fields_to_remove:
                if field in parent_obj["properties"]:
                    del parent_obj["properties"][field]

    required_paths = get_dict_paths_with_key(schema, "required")
    for path in required_paths:
        parent_obj = get_dict_at_path(schema, path)
        if "required" in parent_obj and isinstance(parent_obj["required"], list):
            parent_obj["required"] = [
                field
                for field in parent_obj["required"]
                if field not in fields_to_remove
            ]

    return schema


# From OpenAI
def ensure_strict_json_schema(
    json_schema: object,
    *,
    path: tuple[str, ...],
    root: dict[str, object],
) -> dict[str, Any]:
    """Mutates the given JSON schema to ensure it conforms to the `strict` standard
    that the API expects.
    """
    if not isinstance(json_schema, dict):
        raise TypeError(f"Expected {json_schema} to be a dictionary; path={path}")

    defs = json_schema.get("$defs")
    if isinstance(defs, dict):
        for def_name, def_schema in defs.items():
            ensure_strict_json_schema(
                def_schema, path=(*path, "$defs", def_name), root=root
            )

    definitions = json_schema.get("definitions")
    if isinstance(definitions, dict):
        for definition_name, definition_schema in definitions.items():
            ensure_strict_json_schema(
                definition_schema,
                path=(*path, "definitions", definition_name),
                root=root,
            )

    typ = json_schema.get("type")
    if typ == "object" and "additionalProperties" not in json_schema:
        json_schema["additionalProperties"] = False

    # object types
    # { 'type': 'object', 'properties': { 'a':  {...} } }
    properties = json_schema.get("properties")
    if isinstance(properties, dict):
        json_schema["required"] = [prop for prop in properties.keys()]
        json_schema["properties"] = {
            key: ensure_strict_json_schema(
                prop_schema, path=(*path, "properties", key), root=root
            )
            for key, prop_schema in properties.items()
        }

    # arrays
    # { 'type': 'array', 'items': {...} }
    items = json_schema.get("items")
    if isinstance(items, dict):
        json_schema["items"] = ensure_strict_json_schema(
            items, path=(*path, "items"), root=root
        )

    # unions
    any_of = json_schema.get("anyOf")
    if isinstance(any_of, list):
        json_schema["anyOf"] = [
            ensure_strict_json_schema(variant, path=(*path, "anyOf", str(i)), root=root)
            for i, variant in enumerate(any_of)
        ]

    # intersections
    all_of = json_schema.get("allOf")
    if isinstance(all_of, list):
        if len(all_of) == 1:
            json_schema.update(
                ensure_strict_json_schema(
                    all_of[0], path=(*path, "allOf", "0"), root=root
                )
            )
            json_schema.pop("allOf")
        else:
            json_schema["allOf"] = [
                ensure_strict_json_schema(
                    entry, path=(*path, "allOf", str(i)), root=root
                )
                for i, entry in enumerate(all_of)
            ]

    # string
    if typ == "string":
        if "format" in json_schema:
            if json_schema["format"] not in supported_string_formats:
                del json_schema["format"]

    # strip `None` defaults as there's no meaningful distinction here
    # the schema will still be `nullable` and the model will default
    # to using `None` anyway
    if json_schema.get("default", NOT_GIVEN) is None:
        json_schema.pop("default")

    # we can't use `$ref`s if there are also other properties defined, e.g.
    # `{"$ref": "...", "description": "my description"}`
    #
    # so we unravel the ref
    # `{"type": "string", "description": "my description"}`
    ref = json_schema.get("$ref")
    if ref and has_more_than_n_keys(json_schema, 1):
        assert isinstance(ref, str), f"Received non-string $ref - {ref}"

        resolved = resolve_ref(root=root, ref=ref)
        if not isinstance(resolved, dict):
            raise ValueError(
                f"Expected `$ref: {ref}` to resolved to a dictionary but got {resolved}"
            )

        # properties from the json schema take priority over the ones on the `$ref`
        json_schema.update({**resolved, **json_schema})
        json_schema.pop("$ref")
        # Since the schema expanded from `$ref` might not have `additionalProperties: false` applied,
        # we call `_ensure_strict_json_schema` again to fix the inlined schema and ensure it's valid.
        return ensure_strict_json_schema(json_schema, path=path, root=root)

    return json_schema


def resolve_ref(*, root: dict[str, object], ref: str) -> object:
    if not ref.startswith("#/"):
        raise ValueError(f"Unexpected $ref format {ref!r}; Does not start with #/")

    path = ref[2:].split("/")
    resolved = root
    for key in path:
        value = resolved[key]
        assert isinstance(
            value, dict
        ), f"encountered non-dictionary entry while resolving {ref} - {resolved}"
        resolved = value

    return resolved


# ? Not used
def generate_constraint_sentences(schema: dict) -> str:
    """
    Generate human-readable constraint sentences from a JSON schema.

    Args:
        schema: JSON schema dictionary

    Returns:
        String containing constraint sentences separated by newlines
    """
    constraints = []

    def extract_constraints_recursive(obj, prefix=""):
        if isinstance(obj, dict):
            if "properties" in obj:
                properties = obj["properties"]
                for prop_name, prop_def in properties.items():
                    current_path = f"{prefix}.{prop_name}" if prefix else prop_name

                    if isinstance(prop_def, dict):
                        prop_type = prop_def.get("type")

                        # Handle string constraints
                        if prop_type == "string":
                            min_length = prop_def.get("minLength")
                            max_length = prop_def.get("maxLength")

                            if min_length is not None and max_length is not None:
                                constraints.append(
                                    f"    - {current_path} should be less than {max_length} characters and greater than {min_length} characters"
                                )
                            elif max_length is not None:
                                constraints.append(
                                    f"    - {current_path} should be less than {max_length} characters"
                                )
                            elif min_length is not None:
                                constraints.append(
                                    f"    - {current_path} should be greater than {min_length} characters"
                                )

                        # Handle array constraints
                        elif prop_type == "array":
                            min_items = prop_def.get("minItems")
                            max_items = prop_def.get("maxItems")

                            if min_items is not None and max_items is not None:
                                constraints.append(
                                    f"    - {current_path} should have more than {min_items} items and less than {max_items} items"
                                )
                            elif max_items is not None:
                                constraints.append(
                                    f"    - {current_path} should have less than {max_items} items"
                                )
                            elif min_items is not None:
                                constraints.append(
                                    f"    - {current_path} should have more than {min_items} items"
                                )

                        # Recurse into nested objects
                        if prop_type == "object" or "properties" in prop_def:
                            extract_constraints_recursive(prop_def, current_path)

                        # Handle array items if they have properties
                        if prop_type == "array" and "items" in prop_def:
                            items_def = prop_def["items"]
                            if isinstance(items_def, dict) and (
                                "properties" in items_def
                                or items_def.get("type") == "object"
                            ):
                                extract_constraints_recursive(
                                    items_def, f"{current_path}[*]"
                                )

            # Also recurse into other nested structures
            for key, value in obj.items():
                if key not in [
                    "properties",
                    "type",
                    "minLength",
                    "maxLength",
                    "minItems",
                    "maxItems",
                ] and isinstance(value, dict):
                    extract_constraints_recursive(value, prefix)

    # Start extraction from the root schema
    extract_constraints_recursive(schema)

    return "\n".join(constraints)
