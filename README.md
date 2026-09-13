Packed Football - WIP

A PvP football manager game that is all about opening packs! Open packs to get stronger players, get better gear and upgrade them!
Special players will be awarded at each footballing event (ie UCL, WC).
And many more features that surely will be added if POC successful

POC goals:
Play a game! (very fixed, only 442 and random players)
Open a pack! (ts is easy af)
Play a game with that player!


Intended goals and completion rate:
Immersive gameplay (not just a text based action, goal is to actually have agents take decision real time with tendencies and hidden stats) - 80%
Pack mechanincs - 100%
Social mechanics - 30% 
PvP - 0%

Setup:
See mobile/README.md (Godot client) and backend/README.md (Cloud Run backend) for current setup instructions. packedfootball/ is now just the shared game-logic modules the backend reuses (gameEngine, packEngine, player/*, game_state, formations, replay) -- the original pygame/pygbag client that used to live there has been removed.
