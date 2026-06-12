# How the Personally Identifiable Information filter protects personal data in chats

> **Beta** This feature is new and still being refined. Detection is good but
> not perfect treat it as a strong safeguard, not a guarantee.

The Personally Identifiable Information (PII) filter is a per-chatbot toggle that removes personal data from a
user's message **before it is sent to the large language model**, then restores it
in the answer shown back to the user. The model never sees the raw personal
data; the user still reads a natural reply with their own details intact.

## What it does

When a user writes something like:

> Hi, my name is Marie Dupont, my email is marie@example.lu

the filter detects the personal data and the model actually receives:

> Hi, my name is [FIRSTNAME_1] [LASTNAME_1], my email is [EMAIL_1]

If the model's answer echoes one of these placeholders, the filter swaps the
original value back in, so the user sees their real name and email and not the
placeholder.

When personal data is detected and removed from a message, the user is also
shown a warning so they know it happened:

> Personal data was detected and removed from your message before it reached the
> AI. As a precaution, please avoid sharing personal information in this chat.

It detects names, email addresses, phone numbers, addresses, IBANs, credit
cards, national IDs and similar identifiers, in English, French and German and other EU languages.

Detection is handled by a dedicated machine-learning model trained to recognise
personal data across all 26 official EU languages. It runs as a separate service
alongside the rest of the services.

## How to enable it

1. Open the chatbot you want to protect and go to the **Settings** tab.
2. Find **Personally Identifiable Information (PII) Filter** and toggle it on.
3. That's it new messages to this chatbot are filtered from then on.

## Good to know

- Filtering adds a short delay per message (typically under a second) while the message is scanned.
- Detection can occasionally miss an unusual name or, more rarely, flag a common word. 
- The user's data is restored only when the model repeats the placeholder exactly. If the model paraphrases ("your last name"), there is nothing to restore, which is expected.
