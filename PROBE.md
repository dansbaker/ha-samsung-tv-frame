# Local Art API probe

Target: 2024 Frame LS03D, normal watching mode, authenticated local Art channel. A read-only `get_content_list` request without category returned an event named `get_content_list`, correlated by `request_id`, with a JSON-encoded `content_list` string containing 112 records. Records contained category, content type, dimensions, image date, matte, slideshow and content ID fields. No timeout was observed. A JPEG upload without selection returned a newly assigned content ID, which appeared in a subsequent list. Deleting that ID returned success, and a subsequent list confirmed removal. No pre-existing content was changed. Probe did not test offline or timeout conditions.

# Tokenless Art reconnect, watching mode

On the authorized 2024 LS03D, a secure Art websocket with the previously approved integration client name and no token returned `get_content_list` with 112 records. The user confirmed no TV authorization prompt. A separate previously approved probe client also listed 112 records tokenless without a prompt. A token-bearing Art reconnect during HA restart produced a user-observed Home Assistant authorization prompt despite First Time Only. This proves a viable tokenless read on this model, not compatibility across other models or firmware. Remote-control pairing remains separate. No content was changed in these probes.
