# Redis Shared Memory + Playbook for ChatGPT

This plugin gives ChatGPT a shared team memory. Once it is set up you can ask
ChatGPT things like:

- "What did we decide about the colours for the Real Reaction project?"
- "What are my open action items?"
- "I finished the trend-watching research. Publish that update for the team."
- "Prepare the management review agenda for next week."

ChatGPT answers from a shared Redis memory that your whole team uses, and it
shows where every answer came from. It never shares anything you say until you
review the exact update and confirm it.

This guide takes you from an empty Redis Cloud account to a working demo in
about 45 minutes. You will create two services in the Redis Cloud console, run
one setup command, and install the plugin in ChatGPT.

Developers who want to know how it works should read
[docs/how-it-works.md](docs/how-it-works.md) and [AGENTS.md](AGENTS.md).

---

## What you need

- **A Mac** with the **ChatGPT desktop app** installed and signed in, with
  plugins available on your account.
- **A Redis Cloud account** at [cloud.redis.io](https://cloud.redis.io). A new,
  free account is enough; everything below uses the free database.
- **Python 3.11 or newer.** Step 1 checks this.
- **About 45 minutes.**

You will type a few commands into **Terminal**. Each one is shown in a grey
box: copy the whole box, paste it into Terminal, and press **Return**. To open
Terminal, press **⌘ Space**, type `Terminal`, and press **Return**.

The console shows each API key **only once**. When a step creates a key, copy
it into your password manager straight away; you paste it again in Step 9.
**Never paste a key into a ChatGPT chat, an email, or a Slack message.**

---

## Part 1: Get the project

### Step 1: Check that Python is installed

Paste this into Terminal:

```sh
python3 -c 'import sys; print("Python", sys.version.split()[0], "OK" if sys.version_info >= (3, 11) else "TOO OLD")'
```

You should see a line ending in **OK**.

**If you see `TOO OLD` or "command not found":** install the latest Python from
[python.org/downloads](https://www.python.org/downloads/macos/) (or ask IT for
the approved version), close Terminal, open it again, and repeat this step.

### Step 2: Download the project

Paste this into Terminal. It downloads the project into a folder in your home
directory and moves into it:

```sh
cd ~ && git clone https://github.com/redis-field-engineering/ram-and-playbook-codex-plugin.git && cd ram-and-playbook-codex-plugin
```

If macOS asks to install the **command line developer tools**, click
**Install**, wait for it to finish, and paste the command again.

Every later Terminal command in this guide runs from this folder. If you open a
new Terminal window, first paste `cd ~/ram-and-playbook-codex-plugin`.

---

## Part 2: Create the Redis Cloud services

Sign in at [cloud.redis.io](https://cloud.redis.io). Everything in this part
happens in the console under **Iris** in the left-hand menu.

### Step 3: Create the Agent Memory service

1. Select **Agent Memory**, then **Create Agent Memory service**.

   ![The Agent Memory page with its Create button](docs/images/getting-started/console-01-agent-memory-landing.png)

2. Enter a **Service name**, for example `real-reaction-demo`. Leave
   **Database** set to **Free Redis database**, and select **Create**.
   Creating the service takes up to two minutes.

   ![The Create Agent Memory service dialog](docs/images/getting-started/console-02-create-dialog.png)

3. When **Connect to Agent Memory** appears, note that the **Endpoint** and
   **Store ID** are shown here and on the service page; you need them in
   Step 9. Select **Skip for now**. You create the API key in Step 6.

   ![The Connect to Agent Memory dialog showing the endpoint and store ID](docs/images/getting-started/console-03-connect-dialog.png)

### Step 4: Add the memory type

The demo stores its records in one custom memory type with nine fields. The
console only lets you add it after the service exists, and **fields cannot be
changed once saved**, so check each one before saving.

1. On the service's **Configuration** tab, select **Edit**.

   ![The service Configuration tab with its Edit button](docs/images/getting-started/console-04-service-configuration.png)

2. Under **Memory types & extraction**, select **Add type** and enter:
   - **Name:** `organizational_state`
   - **Description:** `Organizational-state observations and current-state projections for management review.`
   - Switch **Use for session extraction** off, so it reads **Not used for
     session extraction**. Leave **Extraction prompt** empty.

   ![The new memory type with session extraction switched off](docs/images/getting-started/console-05-memory-type.png)

3. Under **Custom fields**, select **Add field** once for each row below. Type
   the name exactly, choose the type, and paste the description:

   | Field | Type | Description |
   | --- | --- | --- |
   | `schema_version` | str | `Record contract version, such as organizational-state-v3.` |
   | `state_kind` | str | `One of: action_item, decision, risk, issue, dependency, approval, conflict.` |
   | `lifecycle_status` | str | `Lifecycle state, such as open, in_progress, decided, or completed.` |
   | `project_id` | str | `Canonical project ID, such as project-ami-es2002.` |
   | `meeting_id` | str | `Canonical meeting ID, or empty.` |
   | `accountable_entity_id` | str | `Canonical ID of the accountable person, or empty.` |
   | `conflict_status` | str | `Projections only: conflict state. Empty on observations.` |
   | `record_kind` | str | `observation for extracted or promoted evidence; projection for current state.` |
   | `details` | **object** | `Every other attribute as one JSON object, with the exact keys listed in the extraction prompt.` |

   ![The nine custom fields filled in](docs/images/getting-started/console-06-memory-type-fields.png)

4. Check the names and types once more, then select **Save** at the top of
   the page. The section now shows `organizational_state` with **9 fields**.

   ![The saved memory type showing 9 fields](docs/images/getting-started/console-07-memory-type-saved.png)

### Step 5: Create the document extractor

The extractor reads the demo documents and turns them into memory records.

1. Copy the extraction prompt to your clipboard by pasting this into Terminal:

   ```sh
   pbcopy < context-models/management-agenda/v1/extraction-prompt-compact.txt
   ```

2. In the console, open the service's **MemoryETL** tab and select
   **New extractor**.

   ![The MemoryETL tab with no extractors](docs/images/getting-started/console-08-memoryetl-tab.png)

3. Enter the **Name** `organizational-state-documents`, keep **Memory type**
   set to `organizational_state`, and leave **Destination namespace** empty.
   The setup command moves what it extracts into the project's shared
   namespace, `real-reaction`.
   Switch on **Customize extraction prompt for documents** and paste the prompt
   (**⌘ V**) into the box that appears. Select **Save**.

   ![The New extractor form with the prompt pasted](docs/images/getting-started/console-09-new-extractor.png)

4. The saved extractor shows a REST API example. Its `"extractorId"` value,
   starting `ex_`, is the **extractor ID** you need in Step 9.

   ![The saved extractor with its extractor ID in the REST API example](docs/images/getting-started/console-10-extractor-saved.png)

### Step 6: Create the Agent Memory API key

1. Open the service's **Configuration** tab and select **Create API key**.
2. Keep the access set to **read** and **write**, then select
   **Create API key**.
3. Copy the key into your password manager now. The console does not show it
   again.

   ![The Create API key dialog for Agent Memory with read and write selected](docs/images/getting-started/console-11-create-api-key.png)

### Step 7: Create the Playbook and publish the agenda Skill

The Playbook holds the instructions ChatGPT follows to prepare an agenda.

1. Build the Skill package by pasting this into Terminal:

   ```sh
   python3 scripts/package_skill.py
   ```

   It creates `dist/prepare-management-review-agenda.zip` and prints the values
   for the upload form. Keep that output open.

2. In the console, select **Agent Playbooks**, then **New Playbook**.

   ![The Agent Playbooks page with its New Playbook button](docs/images/getting-started/console-12-playbooks-landing.png)

3. Enter a **Name**, for example `real-reaction-agenda`. Keep the free
   database and the default embedding model, and select **Create Playbook**.

   ![The New Playbook dialog](docs/images/getting-started/console-13-new-playbook.png)

4. When **Connect to Playbook** appears, note the **Endpoint** and
   **Playbook ID**; you need them in Step 9. Select **Skip for now**.

   ![The Connect to Playbook dialog showing the endpoint and playbook ID](docs/images/getting-started/console-14-playbook-connect.png)

   The same values are on the Playbook's **Configuration** tab, as **Agent
   endpoint** and **Playbook ID**.

   ![The Playbook Configuration tab showing the agent endpoint and playbook ID](docs/images/getting-started/console-15-playbook-page.png)

5. Open the **Registry** tab, choose **Skills**, and select **Upload Skill**.

   ![The Playbook Registry tab showing Skills and Upload Skill](docs/images/getting-started/console-16-playbook-registry.png)

6. Choose `dist/prepare-management-review-agenda.zip` from the project folder.
   Open **Optional settings** and paste the values that `package_skill.py`
   printed:
   - **Alias:** `prepare-management-review-agenda`
   - **Retrieval intents:** the five intents, one per line
   - **Filter attributes (JSON):** the JSON line

   The alias matters: the plugin finds the Skill by it. Select **Upload Skill**.

   ![The Upload Skill dialog with the ZIP and optional settings filled in](docs/images/getting-started/console-17-upload-skill.png)

7. The Skill appears as **v1**, unpublished. Select **Publish version**, then
   **Publish**.

   ![The uploaded Skill showing v1 unpublished](docs/images/getting-started/console-18-skill-uploaded.png)

   ![The Skill showing Published v1](docs/images/getting-started/console-19-skill-published.png)

### Step 8: Create the Playbook read-only key

The plugin only reads from the Playbook, so give it a read-only key.

1. Select **Connect** at the top of the Playbook page, then **Create an API key**.
2. Under **What can this key do**, uncheck **full** so that only **read** stays
   selected. The summary reads **Agent Playbooks · 1 resource · read**.
3. Select **Create key** and copy the key into your password manager.

---

## Part 3: Connect your computer

### Step 9: Run the setup command

This one command connects your Mac to the services and installs the plugin in
ChatGPT.

1. Quit ChatGPT completely: click its window and press **⌘ Q**. Setup changes
   ChatGPT's plugin settings, and ChatGPT reads them when it starts. If
   ChatGPT is still open, setup reminds you.
2. Paste this into Terminal from the project folder:

   ```sh
   python3 scripts/setup_demo.py
   ```

It asks for each value in turn. Keys are not shown as you type.

| It asks for | Where to find it |
| --- | --- |
| Agent Memory endpoint | Agent Memory service → **Configuration** → **URL List** (Step 3) |
| Store ID | Agent Memory service → **Configuration** → **Store ID** (Step 3) |
| Agent Memory API key | Your password manager (Step 6) |
| MemoryETL extractor ID | **MemoryETL** tab → the `ex_…` value in the REST API example (Step 5) |
| Playbook agent endpoint | Playbook → **Configuration** → **Agent endpoint** (Step 7) |
| Playbook ID | Playbook → **Configuration** → **Playbook ID** (Step 7) |
| Playbook API key | Your password manager (Step 8) |
| Your participant name | Pick `andrew`, `craig`, `david`, or `laura`; each has demo work assigned |

The command then:

- saves your settings to a private file only your user account can read;
- checks both services;
- loads the three demo documents into the project's shared space and builds
  the team's current view. This takes a few minutes;
- installs the plugin in ChatGPT;
- limits the plugin to this project folder. ChatGPT installs plugins for your
  whole account, so without this its tools and hooks would run in all your
  other projects too. The project's own settings file (`.codex/config.toml`)
  switches it back on here;
- asks **Trust this folder now?** Press **Return** for yes. ChatGPT only reads
  the project's settings file, the one that switches the plugin on, in a
  folder you trust; and
- prepares the plugin's helper program, so your first chat isn't slow.

It finishes with **Setup complete**.

![Terminal showing the setup command finishing with Setup complete](docs/images/getting-started/local-02-terminal-setup-complete.png)

You can run the command again at any time. It offers your saved values as
defaults, skips documents that are already loaded, and refreshes the plugin.

### Step 10: Open the project in ChatGPT

1. Open ChatGPT.
2. Create a ChatGPT project for the project folder. The plugin is switched on
   only in chats there.
   1. Above the message box, click **Choose project**, then **New project**.

      ![The Choose project button above the ChatGPT message box](docs/images/getting-started/local-07-chatgpt-choose-project.png)

   2. Name it, for example `Real Reaction demo`. Under **Source folders**,
      click **Add** and choose the `ram-and-playbook-codex-plugin` folder.
      Click **Create project**.

      ![The Create project dialog with a name field and Source folders](docs/images/getting-started/local-07b-chatgpt-create-project.png)

3. Start a new chat in that project. If ChatGPT asks whether to trust the
   folder, choose to trust it. Send:

   > Check the Redis Shared Memory connection status.

### Step 11: Allow private capture and check the connection

The plugin includes two small "hooks". When you send ChatGPT a message, a hook
keeps a private copy, and the plugin saves it to **your own personal memory
space** so the assistant
can turn a reported update into a proposal for you to review. Hooks never
share anything with your team, and ChatGPT will not run them until you approve
them.

After your first message, ChatGPT shows **Review hooks** with the plugin's two
hooks:

- **Capturing private memory intent** runs when you send a message.
- **Recording private session end** runs when a chat ends.

![ChatGPT's Review hooks dialog with Allow all and Allow selected](docs/images/getting-started/local-06-chatgpt-review-hooks.png)

1. To see what a hook runs, open it with the arrow on the right. Both run
   `capture.py` from the Redis Shared Memory + Playbook plugin. They only write
   to a private file on your Mac and make no network calls. The plugin itself
   sends your messages to your personal memory space.
2. Select **Allow all**. If the dialog also lists hooks from other plugins,
   tick only these two and select **Allow selected**.

   If you choose **Not now**, the plugin still works, but it won't capture
   your updates. You can allow the hooks later in ChatGPT's settings. You are
   asked again only if a future version changes the hooks.
3. ChatGPT may ask permission before using the plugin. Allow it.

You should see that the connection is **verified**, with your namespace,
your participant name, and the plugin version.

If anything shows as an error, see [If something goes wrong](#if-something-goes-wrong).

You are set up. 🎉

---

## Part 4: Take the guided tour

The demo data is the fictional **Real Reaction** team designing a TV remote
control, from the [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/)
kick-off minutes and final report, plus one short synthetic action log written
for this tour. Send these prompts in order in a **new chat in the project you
created in Step 10**. If ChatGPT does
not use the plugin on its own, add "use the Redis Shared Memory plugin" to your
message.

**The meetings took place in December 2004**, so most answers cite 2004
dates. Updates you publish are dated today. ChatGPT may point out that the
records are old and suggest checking whether they still apply. That's
expected: it reports what the evidence says and doesn't assume nothing has
changed since.

1. **Recall decisions**

   > What are the final decisions regarding color for the Real Reaction project?

   Look for: the corporate colour and final materials and colours decisions
   from the final report, each with its source.

2. **Your own work**

   > What are my open action items?

   "Me" is the participant name you chose in Step 9. For `andrew` this is the
   trend-watching research; for `laura`, writing and uploading the meeting
   minutes. Missing due dates are reported as missing, not invented.

3. **Report a finished task**

   > I have completed the trend-watching research. Please publish this update
   > to the Real Reaction shared memory, but show me the exact update first.

   Use your own open action from prompt 2 if you are not `andrew`. Look for:
   ChatGPT shows the exact proposed change from `open` to `completed` and asks
   you to confirm. **Nothing is shared yet.**

4. **Confirm it**

   > Yes, publish it to shared memory.

   Look for: a confirmation that the update was published and that the team's
   current view is updated. Publish it only once. Ask prompt 2 again: the
   action is now completed, for you and for everyone else using the project.

5. **Prepare an agenda** (this takes about two minutes)

   This is where the Playbook comes in. ChatGPT doesn't decide on its own
   what belongs on a management agenda. It follows the agenda Skill you
   published in Step 7:

   ```text
   Your request ──► ChatGPT ──► plugin ──┬──► Agent Playbook
                                         │      the published Skill
                                         │      prepare-management-review-agenda,
                                         │      every rule file checked unchanged
                                         │
                                         └──► Agent Memory
                                                the current items and their sources
                                                       │
                                                       ▼
                                   an agenda drafted by the Skill's rules,
                                   every topic tied to its source
   ```

   The Skill's five rule files set:
   - what the review is for and who attends;
   - what earns a place on the agenda;
   - the shape of each topic;
   - which items count as current or settled;
   - when to leave something out or flag it for a decision.

   Change the rules in the Playbook, and every participant's next agenda
   follows them. Nothing changes in the plugin or on anyone's Mac.

   > Prepare an evidence-backed management review agenda for the Real Reaction
   > project for 15 November 2026. Use at most eight management topics. Keep the
   > action register, completed work, confirmed decisions, conflicts, and agenda
   > topics separate.

   Look for: the trend-watching research under completed work, the other
   three actions still open with no invented due dates, and topics that
   each cite their sources.

   ![The agenda's action register: Andrew's research completed, three actions open](docs/images/getting-started/local-10-chatgpt-agenda.png)

   ![The agenda's eight management topics with leads, requested outcomes, and timings](docs/images/getting-started/local-11-chatgpt-agenda-topics.png)

6. **See which rules it followed**

   > Which Playbook Skill and version did you use for that agenda, and which
   > rule files did you check?

   Look for: `prepare-management-review-agenda`, the version shown in your
   Playbook's **Registry** in the console (Step 7), and the Skill plus its five
   rule files, each verified. The plugin checks every file against the
   fingerprint recorded in the published Skill, and refuses to prepare the
   agenda if one doesn't match.

7. **Ask about history**

   > What is the entire history of the LCD discussion?

   Look for: the LCD and talk-back decisions, then the later decision that
   removed the LCD and the advanced chip.

8. **Ask a precise question**

   > Has Laura already published the meeting minutes?

   Look for: Laura's minutes action, still open because nobody has published a
   completion for it.

Presenters should also read the
[full demo runbook](docs/management-agenda-demo-runbook.md).

---

## If something goes wrong

| What you see | What to do |
| --- | --- |
| Python is `TOO OLD` | Install Python from python.org (Step 1), then reopen Terminal. |
| Setup: "ChatGPT's codex program was not found" | Install the ChatGPT desktop app in **Applications**, then run the setup command again. |
| The setup command says a value does not look right | Copy it again from the console. The command repairs extra spaces, quotes, and pasted paths, and asks again. |
| Setup: "Agent Memory: RAM rejected the API key" | The Agent Memory key is wrong or expired. Create a new one (Step 6) and run the setup command again. |
| Setup: "Playbook: … not discovered" | The Skill is not published, or its alias is not `prepare-management-review-agenda`. Repeat Step 7. |
| Setup: "memory type … is not registered" | The memory type is missing or misnamed. Check Step 4. |
| Setup: "ChatGPT's plugin list points at another copy of this project" | You downloaded the project twice. Answer **y** to use this folder, or run setup from the other folder. |
| ChatGPT doesn't use the plugin, or says its tools aren't available | Start the chat in the project you created in Step 10, and trust its folder if asked. If ChatGPT was open while setup ran, quit (**⌘ Q**) and reopen it. The plugin is switched off everywhere else. |
| "The exact statement was not found in this user's private hook capture" | The chat isn't in the project you created in Step 10, so your message wasn't captured. Start a new chat in that project and send the update again. |
| `configuration_missing` or `configuration_invalid` | Run the setup command again (Step 9). |
| `authentication_failed` or `playbook_authentication_failed` | A key is wrong or expired. Create a new one and run the setup command again. |
| `network_error` or `playbook_unavailable` | Check your internet and VPN connection. |
| The first chat is very slow or times out | Run the setup command again (Step 9); it prepares the plugin's helper program. |
| Your updates are not being captured | Allow the plugin's two hooks in ChatGPT's settings (Step 11), then quit and reopen ChatGPT. |
| ChatGPT says the update was saved but the current view will update later | Paste `.venv/bin/python scripts/reconcile_management_state.py --apply` into Terminal from the project folder. Do not publish the update again. |

For every error code and more detail, see the troubleshooting table in
[CODEX_INSTALLATION.md](CODEX_INSTALLATION.md#troubleshooting).

## Updating or removing the plugin

- **Update:** quit ChatGPT (**⌘ Q**), then paste this into Terminal from the
  project folder and press **Return** at each question to keep your values:

  ```sh
  git pull && python3 scripts/setup_demo.py
  ```

  Open ChatGPT again. If the new version changed the hooks, ChatGPT shows
  **Review hooks** again; allow them as in Step 11.
- **Remove:** quit ChatGPT, then run `python3 scripts/setup_demo.py --remove`.
  Your settings file stays on your Mac until you delete it, and nothing is
  deleted from Agent Memory.

## Privacy in one paragraph

Your keys stay in a private file on your Mac that only your user account can
read. The plugin runs only in chats in the project folder. What you type there
is saved only to your personal memory space, and nothing is captured from your
other projects. Nothing
reaches the shared team memory unless ChatGPT shows you the exact update and
you confirm it. Your participant name labels your contributions but is not a
login; access is controlled by your keys. Details are in
[SECURITY.md](SECURITY.md).

## More documentation

- [CODEX_INSTALLATION.md](CODEX_INSTALLATION.md): the full participant
  reference, including every setting and troubleshooting code
- [DEMO_ENVIRONMENT_SETUP.md](DEMO_ENVIRONMENT_SETUP.md) and
  [HANDOVER.md](HANDOVER.md): administrator details and the scripted setup
- [docs/how-it-works.md](docs/how-it-works.md): architecture, the context
  model and its storage layouts, the quality gate, and boundaries
- [docs/management-agenda-demo-runbook.md](docs/management-agenda-demo-runbook.md):
  presenter notes
- [AGENTS.md](AGENTS.md) and [SECURITY.md](SECURITY.md): for maintainers
