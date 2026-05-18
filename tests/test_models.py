"""Tests for AI Card data models."""

from nanobot_channel_dingtalk.models import AICardInstance, AICardStatus


class TestAICardStatus:
    """AICardStatus enum values match DingTalk API spec."""

    def test_status_values(self):
        assert AICardStatus.PROCESSING == "1"
        assert AICardStatus.INPUTING == "2"
        assert AICardStatus.FINISHED == "3"
        assert AICardStatus.EXECUTING == "4"
        assert AICardStatus.FAILED == "5"


class TestAICardInstance:
    """AICardInstance dataclass defaults and creation."""

    def test_default_status(self):
        instance = AICardInstance(
            card_instance_id="test_id",
            robot_code="test_robot",
            target={"openConversationId": "conv123"},
        )
        assert instance.card_instance_id == "test_id"
        assert instance.robot_code == "test_robot"
        assert instance.target == {"openConversationId": "conv123"}
        assert instance.status == AICardStatus.PROCESSING
        assert instance.created_at > 0

    def test_custom_status(self):
        instance = AICardInstance(
            card_instance_id="id2",
            robot_code="robot2",
            target={"receiverUserId": "user1"},
            status=AICardStatus.FINISHED,
        )
        assert instance.status == AICardStatus.FINISHED
