# Home Assistant / HACS

This repository includes a Home Assistant custom integration in
`custom_components/wyze_garmin_sync`. It exposes the latest Wyze Scale reading
for each detected household profile and uploads a newly detected reading to
that profile's configured Garmin Connect account.

The integration does not import or replay historical measurements. It queries
Wyze's latest-record endpoint for each scale profile and never calls the
time-range history endpoint. Existing historical backfill remains available
through the original standalone script when run manually.

## Install through HACS

1. In HACS, add this repository as a custom integration repository.
2. Install **Wyze Garmin Sync** and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration** and select
   **Wyze Garmin Sync**.
4. Enter the Wyze email, password, API key ID, and API key.
5. After the first refresh discovers the scale profiles, open the integration's
   options, set the poll interval in minutes, and select a Wyze profile to enter
   its Garmin account credentials. Repeat the options step for each profile.
6. If Garmin requests MFA while adding an account, enter the current MFA code.
   The code is used for that login and is not stored.

## Identify which Wyze profile is yours

Before assigning Garmin accounts, use Home Assistant's per-profile **Weight**
sensors to match Wyze profiles to people:

1. Go to **Settings → Devices & services → Wyze Garmin Sync** and open the
   integration's devices/entities. Each profile device has its Wyze name (or
   profile ID) and a **Weight** sensor. The sensor's `profile_id` attribute
   gives the exact profile ID used by the Garmin-account selector.
2. Compare the latest weight shown for each profile with a recent reading you
   can identify in the Wyze app or already know for that person.
3. If the existing readings are ambiguous, leave Garmin accounts unassigned,
   have one person take a new measurement, then press **Sync now** and refresh
   the entity view. The profile whose measurement time and weight changed is
   that person. Repeat with the other household member.
4. In integration options, select the matching profile and add that person's
   Garmin account.

Do the profile matching before linking Garmin accounts so a test measurement
cannot be sent to the wrong Garmin account.

The Wyze account is shared across profiles. Garmin credentials are mapped by
the Wyze profile identifier, and each profile gets its own token directory.
Profile sensor attributes include `profile_id` to make account mapping
unambiguous.

## Entities and manual sync

Each discovered profile has sensors for weight, body fat, body water, bone
mass, muscle mass, basal metabolic rate, metabolic age, visceral fat rating,
BMI, physique rating, and **Last weigh-in**. The last-weigh-in sensor reports
the timestamp supplied by Wyze for the measurement, rather than the time Home
Assistant last synchronized. The integration also provides a **Sync now**
button. Pressing it requests an immediate refresh for all profiles; repeated
readings are not uploaded again. It can also be used while identifying profiles
before Garmin accounts are assigned.

The integration checks Wyze every **15 minutes** by default. In the integration
options, users can set the poll interval to any whole number from **10 to 1440
minutes** (10 minutes to 24 hours), or set it to **0** to disable recurring
polling. After the integration's initial setup refresh, sync manually with the
**Sync now** button, or create an automation to trigger syncs on your own
schedule:

```yaml
alias: Sync Wyze scale to Garmin daily
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: button.press
    target:
      entity_id: button.wyze_garmin_sync_sync_now
mode: single
```

Replace `button.wyze_garmin_sync_sync_now` with the actual **Sync now** button
entity ID shown in **Settings → Devices & services → Wyze Garmin Sync**. With
polling disabled, you can press the button any time or use an automation to
trigger syncs on your own schedule.

## Wyze API key or token expires

Wyze access tokens are refreshed automatically when possible. If Wyze rejects
the refresh token, or you replace/revoke the Wyze API key or key ID, create or
retrieve the current API key and key ID from Wyze, then open the integration's
menu and choose **Reconfigure**. Enter the current Wyze email, password, API
key ID, and API key. The integration verifies the credentials and obtains a
fresh token before saving the updated configuration and reloading.

If authentication fails, the existing integration configuration remains in
place; check the credentials and API key in Wyze before retrying.

Wyze API keys are valid for one year. Review or renew them at the
[Wyze Developer API Console](https://developer-api-console.wyze.com/#/apikey/view)
before expiry. If a sync fails because a key expired, Home Assistant creates
or updates a persistent notification with a reminder and recovery instructions.
The notification is dismissed after a successful sync.

## Credentials and tokens

Credentials are stored in the Home Assistant config entry. Cached Wyze and
Garmin tokens are stored under Home Assistant's `.storage/wyze_garmin_sync`
directory, with Garmin tokens separated by profile. Protect the Home Assistant
configuration directory and do not share token files.

If a Garmin token expires and authentication requires a new MFA challenge,
re-enter that account's Garmin credentials and current MFA code in the
integration options to refresh its token.

## Existing Docker workflow

The custom integration is independent of the existing Docker scheduler and
standalone script. The Docker workflow and its manual historical time-window
mode remain available.
