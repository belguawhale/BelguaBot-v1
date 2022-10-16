#!/bin/bash

ps auxw | grep "python3 ./belguabot.py" | grep -v grep > /dev/null

if [ $? != 0 ]
then
    cd ~/discord-bots/BelguaBot
    python3 ./belguabot.py>>console.out
fi

