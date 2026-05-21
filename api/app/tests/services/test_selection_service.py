from app.services.selection_service import SelectionService


class TestSelectionService:
    def test_parse_malformed_json_returns_empty(self) -> None:
        """Don't crash on bad data from DB."""
        assert SelectionService.parse_selections(None) == []
        assert SelectionService.parse_selections("") == []
        assert SelectionService.parse_selections("not json") == []
        assert SelectionService.parse_selections('{"key": "value"}') == []  # not a list

    def test_extract_file_ids_handles_invalid_uuids(self) -> None:
        selections = [
            "file:123e4567-e89b-12d3-a456-426614174000",
            "file:not-a-uuid",
            "file:",
            "course:123",
        ]

        result = SelectionService.extract_file_ids(selections)

        assert len(result) == 1
        assert str(result[0]) == "123e4567-e89b-12d3-a456-426614174000"

    def test_roundtrip_preserves_data(self) -> None:
        """Serialize then parse is identity."""
        original = ["course:1", "course:2", "file:123e4567-e89b-12d3-a456-426614174000"]

        serialized = SelectionService.serialize_selections(original)
        parsed = SelectionService.parse_selections(serialized)

        assert parsed == original
