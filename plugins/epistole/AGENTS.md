# epistole setup runbook

This is the single setup guide for epistole, written for an agent guiding a user. Follow it in order and skip the steps that `--status` shows are done. The user does two things: create their own Google OAuth client once (a browser task), and run one command per account. You do everything else.

## Rules

- Never ask the user to paste a token or the client secret into chat. The client file is imported by path, and tokens are written by the login command.
- Never print or read `client_secret.json` or anything under `tokens/`.
- The login commands open a browser, so the user runs them. In Claude Code they type `!epistole-login ...` at the prompt.
- State only what `--status` or the `accounts` tool reports. Do not guess which step is done.

## 1. Check where things stand

Call the `accounts` tool, or ask the user to run `!epistole-login --status`. Both print the same lines: whether the Google client file is present, then one line per account with its address and either `signed in` or `needs login: <reason>`. The command exits 0 only when every account is signed in.

- `client: missing` and no accounts yet: go to step 2.
- `client: present` and no accounts yet: go to step 4.
- An account `needs login`: go to step 4 for that alias. If the client is also missing, go to step 2 first.
- All accounts `signed in`: sign-in is done, even if the client shows as missing. The client file is needed only to add an account or to sign one in again. Go to step 5 if the user has not chosen attachment folders yet.

## 2. Create a Google OAuth client

Each user creates their own client, so no shared secret ships with the plugin. If you have a browser tool, you may drive the Google Cloud console while the user is signed in, and ask them to confirm each page. Otherwise read the steps to them.

1. Open the Google Cloud console and create a project, for example `epistole`.
2. Enable the Gmail API for that project (APIs and Services, Library, Gmail API, Enable).
3. Open Google Auth Platform. The first time, Google shows a Get started wizard. It asks in order for the app name and a user support email, then the audience (choose External), then a contact email for Google's notices, then agreement to the User Data Policy. Complete it.
4. Under Branding, set the app home page, the privacy policy link and one authorized domain. Google asks for these only to publish the app; the app stays unverified. A user with no domain can use a free GitHub Pages site at `<username>.github.io`. It needs one page saying what the app does (it reads and drafts the user's own mail on their own computer) and one privacy note. Use `<username>.github.io` as the authorized domain.
5. Under Audience, confirm the user type is External.
6. Under Data access, add exactly two scopes: `https://www.googleapis.com/auth/gmail.readonly` and `https://www.googleapis.com/auth/gmail.compose`. Do not add any others.
7. Under Clients, create a client with application type Desktop app. Download its JSON from the dialog that appears right after the client is created, before closing it, because Google shows the client secret only there. If the dialog was closed, open the client's page, add a new client secret, and download from that dialog. A Web application client does not work and is refused on import.
8. Back under Audience, publish the app to production, so its status reads "In production". An app left in Testing mode has its tokens expire after 7 days, and the user would have to sign in every week.

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

- A new alias opens Google's account chooser. The user picks the account, and epistole records `<alias> = "<address Google returned>"` in `accounts.toml` in the epistole home. Existing accounts and folder paths in that file are kept. The command rewrites the file as a whole, so it starts with a comment saying so, and any other comments in it are not kept.
- An alias already in `accounts.toml` is checked against its recorded address. If the user signs in with a different account, nothing is saved and the command says which address it expected.
- An address that is already recorded under another alias is refused.

At Google's consent screen the user must leave both Gmail permission boxes ticked. If either is unticked, the command prints one line saying so, saves nothing, and the user runs it again.

The browser page ends with "Sign-in received". The terminal then prints `<alias> signed in as <address>`. Run `--status` again to confirm. If the sign-in fails for any other reason, the command prints one line with the cause and the command to run again; it never saves a half-finished account.

## 5. Choose attachment folders

Attachments are off until `attach_dirs` in `accounts.toml` lists at least one folder; the first login writes `attach_dirs = []`, and `create_draft` with an attachment says so. Ask the user which folder to allow. Recommend a dedicated folder that holds only files they mean to send, such as `~/epistole-outgoing`. Never suggest `~/Downloads`: it holds the Google client JSON from step 2.7 and usually other private files.

The user adds the line to `accounts.toml` in the epistole home themselves, for example `attach_dirs = ["~/epistole-outgoing"]`, because the recommended `Read(~/.config/epistole/**)` deny rule keeps Claude's file tools out of that folder. Every path in `accounts.toml`, and `EPISTOLE_HOME` if set, must be absolute or start with `~`. A relative path is refused, because the server and `epistole-login` run from different folders.

## University and Workspace accounts

- The Google login can differ from the mail address. Some universities sign in on a subdomain such as `g.example.edu`, or the mail address is an alias of the login. The recorded address is whatever Google returns, so use the account chooser and check the address in the output.
- An administrator can block apps that Google has not verified, or restrict access to Gmail for third-party apps. Sign-in then ends on a Google page saying the app is blocked or that the administrator blocked access, and no code returns to the terminal. The login command gives up after 5 minutes and prints a timeout line. Nothing the user does in epistole fixes this. They ask their administrator to allow the client, or use a personal account.

## WSL and remote shells

The login command prints the sign-in URL if no browser opens. The user opens it in any browser on the same machine. Google then redirects to `http://127.0.0.1:<port>`, which WSL forwards to the Linux side.

Sign-in must run on a machine with a browser, because the redirect port is chosen at random and cannot be forwarded in advance. For a computer with no browser, such as a remote server:

1. On a machine with a browser, install epistole, import the client and sign in each account as above.
2. Copy `accounts.toml`, `client_secret.json` and the `tokens` folder from that machine's epistole home (`~/.config/epistole`) to the same place on the remote one, keeping permissions: `scp -rp`. The home folder is mode 700 and each file is mode 600.
3. Edit the folder paths in the copied `accounts.toml` if they differ on the remote machine.
4. Run `!epistole-login --status` there to confirm.

Treat the copied folder like a password: copy it only over an encrypted channel, and never into chat or a repository.

## When to sign in again

Run `!epistole-login <alias>` again when `--status` or a tool reports that the account needs login. Google's list of reasons a refresh token stops working is at https://developers.google.com/identity/protocols/oauth2#expiration. The ones that apply here:

- the user revoked epistole in their Google account settings;
- the user changed their Google password (Gmail scopes expire on a password change);
- the token has not been used for 6 months;
- the app was in Testing mode when the token was issued, which expires after 7 days even if the app is published later (sign in again after publishing, step 2.8);
- the account has more than 100 live refresh tokens for this client, and Google revoked the oldest;
- an administrator restricted Gmail access, or revoked the app for the organization;
- the token file was deleted or damaged.

## Checking the result

After `--status` shows every account signed in, call `search` with `account` set to one alias and a small query, to confirm Gmail answers. Drafts are created in Gmail, and the `send_draft` tool always asks the user first.

Tell the user what the prompt covers. It gates the `send_draft` tool. The stored token can also send mail, so a script that reads it could send without a prompt. The controls for that are the `Read(~/.config/epistole/**)` deny rule in the README and Claude Code's sandbox. Claude can put any text it has read into a draft body.
