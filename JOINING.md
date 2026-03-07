# Joining the Imagineering Group Chat

The Imagineering group chat is bridged across five platforms. Pick whichever app you already use — everyone sees everyone's messages regardless of platform.

## How it works

All five platforms are connected into a single conversation. When someone sends a message on Discord, it appears on Telegram, WhatsApp, Signal, and Matrix (and vice versa). Replies and reactions work across platforms too. You'll see each person's real name and avatar no matter where they're chatting from.

```
Discord  ──┐
Telegram ──┤
Signal   ──┼──  One conversation, five apps
WhatsApp ──┤
Matrix   ──┘
```

## Choose your platform

### Discord

1. Join the Imagineering Discord server: **https://discord.gg/ccSsd6G8**
2. Find the **#imagineering** channel
3. Start chatting — that's it

### Telegram

1. Open this invite link: **https://t.me/+k-6h9pBzz200ZDJl**
2. Join the "Imagineering with Claude Code" group
3. Start chatting

### WhatsApp

1. Open this invite link: **https://chat.whatsapp.com/H14OTB48bjPEF0IQzSd5tC**
2. Join the group
3. Start chatting

### Signal

1. Open this invite link: **https://signal.group/#CjQKICjnZ-2w-4rfqXPvRsVAiALpP4FRQ8QNjnEKVlC2VGHMEhBD6-xKm6vTBxox_sosyIwO**
2. Join the group
3. Start chatting

### Matrix (for the self-hosters)

Matrix is the protocol that ties everything together. If you're already a Matrix user or want to try it:

1. Use any Matrix client — [Element](https://app.element.io) is the most popular
2. Create an account on any Matrix homeserver (or use ours at `matrix.imagineering.cc`)
3. Join the room: **`#imagineering:imagineering.cc`**

To register on our homeserver, ask Nick for the registration token, then sign in at `https://matrix.imagineering.cc` via Element.

## What to expect

- **Messages just work.** Send a message on your platform, everyone sees it everywhere.
- **Names and avatars.** You'll appear with your platform profile (name and picture) on other platforms.
- **Replies.** Reply threading works across most platform combinations. If you reply to someone on WhatsApp, people on Discord see it as a threaded reply too.
- **Reactions.** Emoji reactions are relayed across platforms (with some limitations between certain platform pairs).
- **Media.** Images, files, and voice messages are bridged across platforms.
- **No account linking needed.** You don't need to sign up for anything extra. Just join on your preferred app.

## How messages appear

On your platform, messages from other platforms show up with the sender's name:

- **If the bridge can puppet the sender** — the message appears as if they're a native user on your platform (their name, their avatar, as a separate "person" in the chat)
- **On Discord and Telegram** — bridged messages use webhooks/relay bots that show the sender's name and avatar naturally
- **On Signal and WhatsApp** — bridged messages appear via puppet users with the sender's real name

## FAQ

**Can I be on multiple platforms at once?**
Yes, but you'll see your own messages echoed back from the other platforms. It works fine, just slightly noisy.

**Do I need to install Matrix?**
No. Matrix is the backbone, but you never need to interact with it directly. Just use whichever app you prefer.

**Is my message history shared?**
Each platform only shows messages from when you joined. There's no shared history backfill across platforms.

**Who runs this?**
Nick, on infrastructure at `imagineering.cc`. The bridges are open source ([mautrix](https://github.com/mautrix)) and the homeserver is [Continuwuity](https://continuwuity.org).

**Something's broken — who do I tell?**
Message Nick on whichever platform you're on, or open an issue on the [GitHub repo](https://github.com/imagineering-cc/matrix-chat-superbridge).
