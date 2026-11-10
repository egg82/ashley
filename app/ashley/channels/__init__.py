"""Channels: how a person is reached and heard. An adapter turns what arrives on its medium into an `model.Inbound`,
hands it to `respond.respond`, and delivers the `model.Outbound` it gets back. The first adapter is `POST /api/messages`
for signed-in devices (`ashley.api.messages`)."""
