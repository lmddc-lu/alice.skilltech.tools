# How to setup content synchronisation between Alice and Moodle

## Requirements

- A Moodle instance (version 4.5 or later).

## Setup instructions

### 1. Install the Content Export plugin

1. Download the Moodle Content Export plugin ZIP file from [github.com/lmddc-lu/moodle-local_contentexport/releases](https://github.com/lmddc-lu/moodle-local_contentexport/releases/).
2. In your Moodle instance, go to **Site administration > Plugins > Install plugins**.
3. Install the Moodle Content Export plugin.

### 2. Enable Moodle web services and create a token

1. In your Moodle instance, go to **Site administration > Server > Overview** (in the *Web services* section).
2. If the status of **Enable web services** is *No*, click on **Enable web services** and check **Enable web services**, then click **Save changes**.
3. If the status of **Enable protocols** does not contain *rest*, click on **Enable protocols**, enable the **REST protocol**, and click **Save changes**.
4. Go to **Select a service**. You should see an automatically created **Content Export Service**. Edit it, click **Show more**, and check **Can download files**.
5. Click on **Create a token for a user**. Choose a name for the token, select a user with administrator privileges, and choose the **Content Export Service**. Pick an appropriate expiry date, and save your changes.
6. Your token will be displayed on the page. Copy it and save it for later.

### 3. Try the token in Alice

You are now ready to try your newly created token.

1. Go to [alice.skilltech.tools](https://alice.skilltech.tools/) and create a new chatbot of type **Moodle Integration**.
2. In the first step, choose a name and description for your chatbot, enter the URL of your Moodle instance (for example, `https://my.moodle.org`), then paste your token. Click **Verify connection**.
3. If the connection verification succeeds, you are good to go. In the next step, you will see your Moodle instance's courses.
