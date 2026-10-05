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
   options. Set the daily sync time and select a Wyze profile to enter its
   Garmin account credentials. Repeat the options step for each profile.
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

Scheduled synchronization runs once daily at the time selected in the
integration options (default **07:00 Home Assistant local time**). The first
refresh runs during setup. If you want syncs more frequently, create a Home
Assistant automation that calls the integration's **Sync now** button at your
preferred times.

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
