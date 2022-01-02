#!/usr/bin/python3 -u
import unittest

from seoperator2 import ThisHostnames, ScheduledEvent, ProcessingRule, ProcessingRuleProcessor


class ThisHostnamesMock(ThisHostnames):

    # noinspection PyMissingConstructor
    def __init__(self, compute_name: str, node_name: str) -> None:
        self.compute_name: str = compute_name
        self.node_name: str = node_name


class ScheduledEventMock(ScheduledEvent):

    # noinspection PyMissingConstructor
    def __init__(self, eventtype: str, durationinseconds: int) -> None:
        self.eventtype: str = eventtype
        self.durationinseconds: int = durationinseconds


class ProcessingRuleProcessorGeneralTests(unittest.TestCase):

    def test_eventype_not_matched(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"]
                })
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Reboot", -1)
        )
        self.assertEqual(res, True)

    def test_stop_on_first_matched_rule(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                    "and-node-name-matches": "*-nodepool_1-*"
                }),
                ProcessingRule({
                    "rule-type": "handle-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                    "and-node-name-matches": "*-nodepool_2-*"
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"]
                })
            ],
            ThisHostnamesMock("aks-nodepool_2-36328368-vmss_18",
                              "aks-nodepool_2-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", -1)
        )
        self.assertEqual(res, True)

    def test_no_rules_matches(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                    "and-node-name-matches": "*-nodepool_1-*"
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"],
                    "and-node-name-matches": "*-nodepool_2-*"
                })
            ],
            ThisHostnamesMock("aks-nodepool_3-36328368-vmss_18",
                              "aks-nodepool_3-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", -1)
        )
        self.assertEqual(res, True)

    def test_no_rules_at_all(self):
        res = ProcessingRuleProcessor(
            [],
            ThisHostnamesMock("aks-nodepool_3-36328368-vmss_18",
                              "aks-nodepool_3-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 5)
        )
        self.assertEqual(res, True)


class ProcessingRuleProcessorDurationLessEqualToTests(unittest.TestCase):

    def test_ignore_if_duration_less_equal_to_unknown_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-less-equal-to": 10
                })
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", -1)
        )
        self.assertEqual(res, True)

    def test_handle_if_duration_less_equal_to_unknown_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "handle-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-less-equal-to": 10
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                }),
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", -1)
        )
        self.assertEqual(res, False)

    def test_ignore_if_duration_less_equal_to_short_duration(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-less-equal-to": 10
                })
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 10)
        )
        self.assertEqual(res, False)

    def test_handle_if_duration_less_equal_to_short_duration(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "handle-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-less-equal-to": 10
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                }),
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 10)
        )
        self.assertEqual(res, True)

    def test_ignore_if_duration_less_equal_to_long_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-less-equal-to": 10
                })
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 30)
        )
        self.assertEqual(res, True)

    def test_handle_if_duration_less_equal_to_long_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "handle-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-less-equal-to": 10
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                }),
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 30)
        )
        self.assertEqual(res, False)


class ProcessingRuleProcessorDurationGreaterEqualToTests(unittest.TestCase):

    def test_ignore_if_duration_greater_equal_to_unknown_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-greater-equal-to": 10
                })
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", -1)
        )
        self.assertEqual(res, False)

    def test_handle_if_duration_greater_equal_to_unknown_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "handle-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-greater-equal-to": 10
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                }),
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", -1)
        )
        self.assertEqual(res, True)

    def test_ignore_if_duration_greater_equal_to_short_duration(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-greater-equal-to": 10
                })
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 10)
        )
        self.assertEqual(res, False)

    def test_handle_if_duration_greater_equal_to_short_duration(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "handle-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-greater-equal-to": 10
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                }),
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 10)
        )
        self.assertEqual(res, True)

    def test_ignore_if_duration_greater_equal_to_long_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-greater-equal-to": 10
                })
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 30)
        )
        self.assertEqual(res, False)

    def test_handle_if_duration_greater_equal_to_long_duration_case(self):
        res = ProcessingRuleProcessor(
            [
                ProcessingRule({
                    "rule-type": "handle-event-if",
                    "event-type-is": ["Freeze"],
                    "and-duration-in-seconds-greater-equal-to": 10
                }),
                ProcessingRule({
                    "rule-type": "ignore-event-if",
                    "event-type-is": ["Reboot", "Redeploy", "Freeze", "Preempt", "Terminate"],
                }),
            ],
            ThisHostnamesMock("aks-default-36328368-vmss_18",
                              "aks-default-36328368-vmss00000i")
        ).all_considered_should_handle(
            ScheduledEventMock("Freeze", 30)
        )
        self.assertEqual(res, True)


if __name__ == "__main__":
    unittest.main()
