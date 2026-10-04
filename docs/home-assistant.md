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
   options. Set the sync interval in hours and select a Wyze profile to enter
   its Garmin account credentials. Repeat the options step for each profile.
6. If Garmin requests MFA while adding an account, enter the current MFA code.
   The code is used for that login and is not stored.

The Wyze account is shared across profiles. Garmin credentials are mapped by
the Wyze profile identifier, and each profile gets its own token directory.
Profile sensor attributes include `profile_id` to make account mapping
unambiguous.

## Entities and manual sync

Each discovered profile has sensors for weight, body fat, body water, bone
mass, muscle mass, basal metabolic rate, metabolic age, visceral fat rating,
BMI, and physique rating. The integration also provides a **Sync now** button.
Pressing it requests an immediate refresh for all configured profiles; repeated
readings are not uploaded again.

Scheduled synchronization defaults to every 24 hours. Change the interval in
the integration options. The first refresh runs during setup.

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
