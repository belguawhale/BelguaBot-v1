# BelguaBot v1
A moderation Discord bot I created back in 2017 to moderate the [Diepcord discord server](https://discord.gg/vJVqhTf). This repo left mainly for historical purposes.

## Features
- Moderation framework
  - Warning points system with scaling auto-punishments
  - Mute system that detects attempts to bypass it
  - Kicking + banning by id
  - Bulk actions for all of the above
- Bulk adding/removing roles
- Custom permissions system with 4 levels: user, staff, admin, owner
- Custom aliases! Custom commands that can run and parameterize other commands
  - Integrates with permissions system so you can set "runnable" and "editable" levels
  - Useful for sending pre-written messages (shoutout to `~!deadchat9`)
  - note: a lot of more complicated use cases involved aliasing `eval` or other owner-only commands, then allowing users to run a more restricted version of them. From a security perspective I do not recommend this D:
- Diep-themed economy system with exponentially big awards
  - Admin commands for messing with users ;)

## Author's notes
This bot served as part of my journey for learning programming! I'm rather fond of it, especially the alias/permissions framework and the economy system.

There's a lot of good examples of bad practises in here, such as putting everything in one file, global variables, not knowing what classes were, star imports, using JSON as a database, copying the folder as source control, giving users a codepath to eval+exec, and the list goes on.

BelguaBot is the end result of the anguish, pride, and joy I experienced building something to solve a problem, with the means and skills I had, and I wouldn't trade that for anything else :).