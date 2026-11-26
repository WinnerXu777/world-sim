# Rules

## End of day: sync the assets to Google Drive
At the end of every working day, the session closing the day (normally the orchestrator) does this:

1. Zip the whole `myassets/` folder into a fresh `myassets.zip`.
2. Upload the new `myassets.zip` to the owner's Google Drive with the Google Drive connector. Put it in the same folder as the current copy (My Drive root; file id of the last known copy: `1lpB29bUfn9r6EHJ9j3pruiF8u_mv-Ffv`).
3. Rename or trash the old copy on Drive only after the owner says yes.
4. Record the new Drive file id in the day's handover, so the next upload knows which file to replace.

Notes:
- `myassets/` and `myassets.zip` are never committed to git.
- If the upload fails or is skipped, say so in the handover. Then the next day's first session does it.
