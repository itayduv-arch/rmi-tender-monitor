# RMI Tender Monitor — Pilot

An isolated, read-only monitor for Israel Land Authority (רמ״י) public tender information. **This repository does not access or modify any other app or repository.**

## Pilot scope

Start with tender **470/2025 (Hod Hasharon)**. The goal is to test access to the **official** RMI website at `apps.land.gov.il` and record whether a real API response is accessible from GitHub Actions. No tender-opening notifications are enabled yet: a search result or future deadline is *not* proof that submissions are open.

## Running

Use the **RMI API connectivity pilot** workflow under Actions > Run workflow. The scheduled workflow also checks daily. Inspect its logs and JSON report artifact. Nonofficial sites and open-source examples are used for technical discovery only; only responses from the official government host are considered evidence.

If the official API fails, the workflow reports the failure instead of claiming no tender changes occurred.
