# RMI Tender Monitor · מעקב מכרזי רמ״י

An **isolated, read-only** daily monitor of the Israel Land Authority's official `apps.land.gov.il` tender API. This repository cannot access the user's other applications or databases.

## Scope and official source

The monitor checks the exact official tender detail API for **470/2025 – הוד השרון**, **182/2025 – גנות** and **149/2025 – צופית**. It also scans the official tender search results for residential-land candidates in **סביון** (RMI settlement code 587) and for neighborhood names mentioning **כפר אז״ר**. Note that the latter is an **incomplete discovery method**, and zero candidates are not proof that no tenders exist.

For each named tender, it records original and revised publication/open/close dates, current official message, submission-readiness clues, eligibility/population codes, counts, official annex/document metadata and prices if supplied by RMI.

The monitor additionally downloads **every advertised official PDF** for those tenders directly from the RMI API, calculates SHA-256 hashes, and extracts initial searchable text where possible. It compares daily metadata and PDF hashes with the previous valid snapshot, so even a modified PDF with the same name may be detected. Extracted Hebrew text may require manual visual checking.

**No third-party content is used to authenticate dates, opening status or eligibility.**

## Automatic checks and where to inspect

- GitHub Actions: [RMI official tender monitor](../../actions/workflows/rmi-probe.yml). Scheduled **daily at 17:15 UTC**; manual Run workflow and push-based test runs are supported.
- Latest verified snapshot: [state/latest.json](state/latest.json). Contains `checked_at_utc`, `status`, `tenders`, `pdf_complete`, `changes`, and discovery coverage.
- Every run uploads [a report artifact](../../actions) with errors even if RMI becomes unavailable.
- The existing, separate **ChatGPT daily automation** is configured to read the snapshot after this job and post important alerts. This repository by itself does not send ChatGPT or phone notifications.

## Safeguards

- The only trusted tender data host is `apps.land.gov.il`.
- A publication date or a future close deadline **does not prove that submissions are open**. An active form or clear explicit official confirmation is required before the monitor reports verified opening.
- A first complete run establishes a comparison baseline; it does not create invented 'new tender' alerts.
- A temporary API/PDF download failure is logged and must not be reported as an actual tender change.
- A failed check does not replace the previous complete snapshot.
- GitHub writes are restricted to this repository's `state/latest.json`; none target Psycho101, IDmed101, Supabase, or any other repository.

## Known limits

The official API's explicit message, online submission readiness, and tender-annex PDFs can be accessed and monitored; **actual browser form completion/eligibility is not tested**. For כפר אז״ר, a separate locality-discovery route may eventually be needed. Receiving a phone push notification depends on ChatGPT's own notification settings; GitHub Actions success does not prove notification delivery.

## Local testing

```bash
python -m pip install requests 'pypdf>=5,<7'
python -m unittest discover -s tests -v
python monitor.py
```
