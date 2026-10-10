# Usage guide

A system that sends you job offers by email every morning and, when you approve one,
generates the adapted CV and the cover letter.

**Status:** private beta. You need an invitation.

If you are looking for the technical detail, it is in the [README](../README.md).

---

## Getting started

The service is a **private beta**. There is no public form: access is by
invitation and the account is created by the administrator.

### Step 1. Ask for your invitation

Write to the administrator and tell them what you are looking for, in your own words. To create
your account they need:

- Full name
- Email, the one you will use to receive the offers
- Free-form profile: what you are looking for

Optional, but the more you fill in, the more precise the offers are:

- Target role (for example "Senior Frontend Developer" or "Tech Lead")
- City, for the hybrid filters
- Preferred work mode: remote, hybrid Madrid, hybrid Barcelona or on-site
- Technical stack
- Minimum annual salary in euros
- LinkedIn, the full URL

### Step 2. Provide your CV Master

The system adapts YOUR CV to each offer, so it needs a base version to start from.

**Option A, recommended.** Upload a `.txt` with your full CV to your Google Drive, make it
public with "anyone with the link can view", and send the link to the administrator.

**Option B.** Send the CV to the administrator and they upload it to the shared folder under the
name `CV_Master_{your_email_with_hyphens}.txt`.

### Step 3. Wait for the first delivery

When the administrator creates your account, the system runs a first search and you receive
your first offers by email. From then on, delivery is daily at 9:00.

If someone visits the service address without an invitation, they only see a page explaining
that it is a private beta. That is normal: there is nothing to fill in.

---

## Day to day

### The morning email

Every day at 9:00 you receive an email with real offers: company, position, salary,
work mode, link and HR contact. Each one has two buttons,
**Approve** and **Discard**, inside the email itself. You do not need to open anything else.

### When you approve an offer

In one or two minutes a second email arrives with:

- The cover letter, personalized for that company and that position
- The link to the adapted CV, a DOCX in your Drive
- A **Send to company** button, which marks the offer as sent and sends you a third
  confirmation email with the contact details

### What you do

You open the CV, review it, and send the email to the company. **The system never sends anything
to the company on its own**: it only leaves it ready for you.

---

## Changing your preferences

Your profile lives in a Notion database. To change your email, stack or salary,
pause deliveries without deleting you, or delete your account, contact whoever invited you.
Later there will be a way to edit your profile yourself.

---

## If something fails

**The service page takes a long time to load.** Wait 60 seconds, the server wakes up
with the first visit of the day. If it is still the same after two minutes, let us know.

**The offers email does not arrive.** Check spam and promotions, and verify the
sender. If it does not appear, let us know, giving the email you registered with.

**I approved an offer and the CV did not arrive.** The flow takes one or two minutes: the model
writes the letter, adapts the CV and uploads it to Drive. If five minutes pass with nothing,
let us know and the logs will be checked.

**The generated CV has another person's data.** Almost certainly your CV Master has not been
uploaded and the system used a fallback one. Check that you uploaded it and let us know.

### Offer statuses

The status names below are shown as they appear in the Notion database (in Spanish).

| Status | What it means |
|---|---|
| Pendiente (Pending) | Just arrived, undecided |
| Aprobado (Approved) | You pressed "Approve", letter and CV on the way |
| En proceso (In progress) | Letter and CV generated, waiting for you to send it |
| Enviado a empresa (Sent to company) | You pressed "Send", application sent |
| Descartado (Discarded) | You pressed "Discard" |
| Rechazado (Rejected) | The company replied that it is a no |
| Caducada (Expired) | The offer is no longer available |

---

## Privacy

- Your profile is in a private Notion database, with access for the administrator only.
- The adapted CVs are stored in Drive, in a folder with your email as its name.
- Generation uses the Claude API (Anthropic) with your CV Master and the offer description.
- No data is sold or shared with third parties.
- To delete your entire account, let us know and it is removed within 24 hours.

---

## Frequently asked questions

**Are the offers real?**
Yes. They come from real job portals: Adzuna, Tecnoempleo and the LinkedIn RSS feeds.
Before reaching you they go through filters for work mode, location and fit with your profile.

**How much does it cost?**
Nothing. It is a closed private beta. If it becomes a commercial product, you will be told first.

**How many offers do I receive?**
Those that pass the filters that day, with a daily cap. Weekends and holidays
too, there is no pause.

**Can I use it from my phone?**
Yes, the emails are adapted for it.

**Can I invite someone?**
Not yet. Send the contact to the administrator and they are added by hand.

---

## Contact

For any incident, question or comment: reply to any email from the system and it reaches
the administrator.
