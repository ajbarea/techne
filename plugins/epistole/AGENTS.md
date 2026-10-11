# epistole setup runbook

This is the single setup guide for epistole, written for an agent guiding a user. Follow it in order and skip the steps that `--status` shows are done. The user does two things: create their own Google OAuth client once (a browser task), and run one command per account. You do everything else.

## Rules

- Never ask the user to paste a token or the client secret into chat. The client file is imported by path, and tokens are written by the login command.
- Never print or read `client_secret.json` or anything under `tokens/`.
- The login commands open a browser, so the user runs them. In Claude Code they type `!epistole-login ...` at the prompt.
- State only what `--status` or the `accounts` tool reports. Do not guess which step is done.

## 1. Check where things stand

Call the `accounts` tool, or ask the user to run `!epistole-login --status`. Both print the same lines: whether the Google client file is present, then one line per account with its address and either `signed in` or `needs login: <reason>`. The command exits 0 only when every account is signed in.

- `client: missing`: go to step 2.
- `client: present` and no accounts: go to step 3.
- An account `needs login`: go to step 4 for that alias.
- All accounts `signed in`: setup is done.

## 2. Create a Google OAuth client

Each user creates their own client, so no shared secret ships with the plugin. If you have a browser tool, you may drive the Google Cloud console while the user is signed in, and ask them to confirm each page. Otherwise read the steps to them.

1. Open the Google Cloud console and create a project, for example `epistole`.
2. Enable the Gmail API for that project (APIs and Services, Library, Gmail API, Enable).
3. Open Google Auth Platform. Under Branding, set the app name, the user support email, the app home page, the privacy policy link and one authorized domain. A personal page on a domain you control is enough.
4. Under Audience, set the user type to External.
5. Under Data access, add exactly two scopes: `https://www.googleapis.com/auth/gmail.readonly` and `https://www.googleapis.com/auth/gmail.compose`. Do not add any others.
6. Under Clients, create a client with application type Desktop app. Download its JSON file. A Web application client does not work and is refused on import.
7. Back under Audience, publish the app to production, so its status reads "In production". An app left in Testing mode has its tokens expire after 7 days, and the user would have to sign in every week.

Expect the "Google hasn't verified this app" screen at sign-in. It appears for any personal client that has not gone through Google's verification, and it is safe here because the client is the user's own. The user chooses Advanced, then continues to the app.

## 3. Import the client

Ask the user for the path of the downloaded file and have them run:

```
!epistole-login --client <downloaded.json> <alias>
```

The command checks that the file is a Desktop app client, keeps a private copy in the epistole home (`~/.config/epistole`, or `EPISTOLE_HOME`), and never prints it. With an alias it continues straight into that account's sign-in. Without one it only imports the file. The user can delete the download afterwards.

## 4. Sign each account in

Run once per account:

```
!epistole-login <alias>
```

An alias is a short name made of letters, digits, `_` and `-`, such as `personal` or `school`. The name `all` is reserved.

- A new alias opens Google's account chooser. The user picks the account, and epistole records `<alias> = "<address Google returned>"` in `accounts.toml` in the epistole home. Existing entries and paths in that file are kept.
- An alias already in `accounts.toml` is checked against its recorded address. If the user signs in with a different account, nothing is saved and the command says which address it expected.
- An address that is already recorded under another alias is refused.

The browser page ends with "Sign-in received". The terminal then prints `<alias> signed in as <address>`. Run `--status` again to confirm.

## University and Workspace accounts

- The Google login can differ from the mail address. Some universities sign in on a subdomain such as `g.example.edu`, or the mail address is an alias of the login. The recorded address is whatever Google returns, so use the account chooser and check the address in the output.
- An administrator can block apps that Google has not verified, or block the compose scope. Sign-in then ends on a Google page saying the app is blocked, or that access is blocked by the administrator, and no code returns to the terminal; the login command times out after 5 minutes. Nothing the user does in epistole fixes this. They ask their administrator to allow the client, or use a personal account.
- A consent screen that lists the readonly scope but not the compose scope means the scope was not added under Data access. Add it, then sign in again.

## WSL and remote shells

The login command prints the sign-in URL if no browser opens. The user opens it in any browser on the same machine. Google then redirects to `http://127.0.0.1:<port>`, which WSL forwards to the Linux side. Tokens are stored per machine, so each computer needs its own sign-in. On a machine with no browser at all, sign-in is not possible there.

## When to sign in again

Run `!epistole-login <alias>` again when `--status` or a tool reports that the account needs login. This happens when:

- the user revoked epistole in their Google account settings;
- the Google password changed and Google invalidated the sessions;
- the token has not been used for 6 months;
- the app is still in Testing mode and 7 days have passed (publish it, step 2.7);
- the token file was deleted or damaged.

## Checking the result

After `--status` shows every account signed in, call `search` with `account` set to one alias and a small query, to confirm Gmail answers. Drafts are created in Gmail and sending always asks the user first.
