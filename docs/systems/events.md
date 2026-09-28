# Events and notifications

## Purpose

The things that matter reach me as macOS notifications, without me asking. An external event (a new
email, a scheduled task) goes to the event bus, is classified by a local model, and reaches me only
if it passes a notification rule.

## Responsibilities

- **Event bus:** receives external events and scheduled tasks.
- **Scheduled tasks:** a cron definition in a module ([extension points](../architecture.md#extension-points)).
- **Gmail watch renewal:** the watch expires after 7 days; a scheduled task renews it every day
  (the watch itself: [Google](../modules/google.md#gmail)).
- **Sleep and wake:** when the Mac wakes, Jarvis syncs what it missed (Gmail through the history ID),
  and doesn't rely only on events that arrived in real time.
- **Idempotency:** every event has an id, and an event that was already handled is dropped.
- **Importance:** rules in config (specific senders, keywords) plus classification by the local
  model (`classifier` role, [LLM](llm.md)). The threshold is calibrated during the first weeks.
- **Notification rules:** one line per rule in the rules file: event, condition, channel.
- **Notifications:** macOS notifications from the app, for important emails and upcoming meetings.
  Clicking one opens its context in the app ([app](app.md)).

**Not responsible for:** acting on events. Any action still goes through [approvals](permissions.md).

## Contracts

All tentative until Phase 8 is detailed: `Event`, `EventBus`, `NotificationRule`,
`ImportanceClassifier`, `Notifier`, `Scheduler`, `CronJob`, `SyncCursor`.

## Config keys

- The notification rules file (event, condition, channel).
- Importance rules: senders and keywords.
- Open question: file name and key names are not specified yet.

## Decisions

- None yet.

## Open questions

- What counts as an important email: see [open decisions](../design.md#open-decisions).
- Until Phase 8, "what's important" (e.g. in the Phase 3 inbox summary) is decided by the LLM only.

## Introduced in phase

- [Phase 8](../plan/README.md#phase-8--events--notifications).
