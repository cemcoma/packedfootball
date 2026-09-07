from dataclasses import dataclass, asdict

position = ["GK","CD","LB","RB","CDM","CM","CAM","LM","RM","CF","LW","RW"]

@dataclass
class Attributes:
    stamina: int = 60
    speed: int = 60
    agility: int = 50
    passing: int = 50
    ballcontrol: int = 50
    defending: int = 50
    dribbiling: int = 50
    shooting: int = 50


class player:
    def __init__(self, fname, lname, position, attributes:Attributes = None):

        #cosmetic
        self.fname = fname
        self.lname = lname
        self.statistics = {"goals": 0,"assists":0,"matches_played": 0}

        #functional
        self.position = position
        if attributes is None:
            self.attributes = Attributes()
        else:
            self.attributes = attributes

    def getAttributes(self):
        return self.attributes

    def passBall():
        pass

    def __str__(self):
        attributes_str = ""
        for aname,aval in asdict(self.attributes).items():
            attributes_str += f"{aname}: {aval}\n"  

        return f"""*** {self.fname} {self.lname} *** 
        Matches Played = {self.statistics.get("matches_played")}
        Goals = {self.statistics.get("goals")}
        Assists = {self.statistics.get("assists")}
        
        *** Attributes ***
        {attributes_str}
        ------------------------
        """

    def __repr__(self):
        return f"Player({self.fname} {self.lname}, {self.position})"


class goalkeeper(player):
    pass