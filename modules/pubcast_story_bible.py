"""
pubcast_story_bible.py — Canonical narrative lore for PubCast Alpha
==============================================================================
Rear View Foresight LLC · Feic Mo Chroí™

This module contains the full story bible for PubCast's narrative layer:
the game mode storyline, the TikTok movie arc, character autobiographical
roots, the double feature premiere, and the thematic spine that ties
the tutorial to the emotional core.

Other modules (room_conductor, jeremy_cricket, character_engine, bots)
can import from here to stay canon-consistent when generating dialogue,
scene descriptions, or contextual AI responses.

NOTE: This is FICTION. The characters are loosely inspired by facets of
the creator's life but they are not autobiographical transcriptions.
There is a happy ending in the fiction. Whether reality follows is TBD.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ════════════════════════════════════════════════════════════════════════════
# CORE THEMATIC SPINE
# ════════════════════════════════════════════════════════════════════════════

THEMES: Dict[str, str] = {
    "main": (
        "You cannot hide from your past. The little things you brush off "
        "add up. Jealousy breeds resentment. Comparison is the thief of "
        "all contentment. But if you listen to the band, you can still "
        "dance along."
    ),
    "art_vs_function": (
        "The eternal tension between creativity and practicality. "
        "Purfluous dreams in golden hour; Pete keeps the fuse box from "
        "blowing. Neither is wrong."
    ),
    "nostalgia_vs_decay": (
        "Loving something too much to admit it is dying. The studio is "
        "a cathedral of obsolete beauty. The pub is the one thing that "
        "still works."
    ),
    "performance_as_survival": (
        "The show must go on even if nobody is watching. Purfluous "
        "performs to an empty theatre with all the stage lights on, "
        "draining the power budget. The bartender finds them glowing "
        "in the morning and never says a word."
    ),
    "found_family_in_failure": (
        "A broken crew that refuses to stop pretending they are making "
        "something great. The magic is in the mess. You do not make art "
        "to be immortal. You make it to keep the lights on for the "
        "people you love."
    ),
    "beauty_curse": (
        "Pete's beauty is part of her curse. If she were plain she "
        "would never have had those opportunities and might have led a "
        "normal life. The world reduces her to it constantly. The "
        "TikTok girl has the same curse updated for the algorithm."
    ),
    "everyone_is_a_whore_now": (
        "The world changed. Everybody sells their intimacy for a "
        "paycheck now — influencers, creators, brands. Pete was just "
        "ahead of the game. Who cares that she used to be one when "
        "the whole economy caught up."
    ),
    "little_dont_matters": (
        "These things you keep brushing off — they add up to trouble. "
        "The script is bad. The wiring is bad. The money is late. The "
        "friends are fake. Each one is small. Together they are a "
        "structural collapse."
    ),
}

THEME_SONG_LYRICS_FRAGMENT: str = (
    "Everyone has a hard life. Everybody has hard money. "
    "Everyone has their costume to bear. "
    "The grass is always greener over there. "
    "These little don't matters add up after a while. "
    "If you have jealousy it breeds resentment. "
    "And comparison's the thief of all your contentment."
)


# ════════════════════════════════════════════════════════════════════════════
# CHARACTER AUTOBIOGRAPHICAL ROOTS
#
# Each character is a facet of the creator. This is fiction — there IS a
# happy ending in the story. Whether reality matches is still open.
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CharacterRoot:
    character_id: str
    archetype: str
    autobiographical_facet: str
    internal_tension: str


CHARACTER_ROOTS: Dict[str, CharacterRoot] = {
    "sir_purfluous": CharacterRoot(
        character_id="sir_purfluous",
        archetype="The Wash-Up",
        autobiographical_facet=(
            "The part that took the hard money because there were no other "
            "moves left. The relic in a mothball suit who is tickled by a "
            "red carpet because he thought his time was over."
        ),
        internal_tension=(
            "Wants to be seen as a visionary but knows he is selling Pete's "
            "soul to fund it. Gets his main-branch spotlight and pretends "
            "not to notice the cost."
        ),
    ),
    "pete": CharacterRoot(
        character_id="pete",
        archetype="The Survivor / The Beautiful Woman",
        autobiographical_facet=(
            "The one who lives it but cannot feel it or see it. Made hard "
            "choices and was punished by the world for living her truth. "
            "Owns her journey — finally — but the past keeps finding new "
            "ways to use her."
        ),
        internal_tension=(
            "Her beauty is obvious enough that people reduce her to it. "
            "She left porn voluntarily and is financially fine but the "
            "way people assume porn before competence is a constant "
            "low-level annoyance that never stops."
        ),
    ),
    "repeat": CharacterRoot(
        character_id="repeat",
        archetype="The Idealist",
        autobiographical_facet=(
            "The young, idealistic, hopeful energy willing to try anything. "
            "The one who flies the flag for the studio against everyone's "
            "wishes because he knows better. He is the heartbeat of the "
            "tech and the secret documentarian."
        ),
        internal_tension=(
            "His idealism keeps running into the wash-up's cynicism and "
            "the survivor's exhaustion. He believes the happy ending is "
            "possible despite the math."
        ),
    ),
    "tiktok_girl": CharacterRoot(
        character_id="tiktok_girl",
        archetype="The Trapped Princess",
        autobiographical_facet=(
            "The part that chose an image and is now being punished for "
            "it. The world will NOT let her out of the peppy poppy "
            "fashion princess box. She built the bars herself but now "
            "the door is locked."
        ),
        internal_tension=(
            "'Am I not allowed to be human?' She is terrified by the fan "
            "drop-off. Her influencer friends are sharing stories that are "
            "mostly not true. Those people are not her friends. They just "
            "loved the image."
        ),
    ),
    "mormon_boy": CharacterRoot(
        character_id="mormon_boy",
        archetype="The Origin / The Foundation",
        autobiographical_facet=(
            "The Level 0 foundation. The one who grew up in the shadow of "
            "the perfect image and the rules of a world that did not have "
            "a place for the woman he was becoming."
        ),
        internal_tension=(
            "Watches the survivor and wants to forgive her. Watches the "
            "idealist and wants to believe. Watches the wash-up and sees "
            "the cost of staying in the game too long."
        ),
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# STORY ARC — THE TIKTOK MOVIE
#
# The main narrative arc of PubCast's game mode. A 17-year-old TikTok
# fashion influencer rents the studio to make HER movie. Chaos follows.
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StoryBeat:
    beat_id: str
    act: int
    title: str
    summary: str
    gameplay_hook: str = ""
    emotional_note: str = ""


STORY_ARC: List[StoryBeat] = [
    # ── ACT 1: THE SELL-OUT ───────────────────────────────────────────────
    StoryBeat(
        "a1_rent", 1, "The Rental",
        "A 17-year-old TikTok fashion influencer with too much money "
        "rents the studio to make her movie. She wrote a self-indulgent, "
        "melodramatic, terrible script called something like 'Wicked "
        "Mother: The Sigma Protocol.' Purfluous is told to take the "
        "money or the studio closes. He almost forces Pete to take a "
        "role — a small part as the cool but wicked evil mother.",
        gameplay_hook=(
            "Player is learning the studio systems by fulfilling the "
            "TikTok girl's vapid requests. Every task is a real tutorial "
            "disguised as a terrible movie shoot."
        ),
        emotional_note=(
            "Pete feels more like a whore than she ever did when she "
            "was actually paid for it. The indignity of selling her art "
            "to someone who does not see her as a person."
        ),
    ),
    StoryBeat(
        "a1_suckered", 1, "Suckered In",
        "Pete gets suckered into doing a couple of lines and stupid "
        "scenes. She is pissed. The player has to step into her shoes "
        "and do her actual job while she is on camera — running the "
        "floor, managing the shoot, keeping the studio alive.",
        gameplay_hook=(
            "Player learns production management by necessity — "
            "filling Pete's role while she is trapped on set."
        ),
    ),
    StoryBeat(
        "a1_grandpa", 1, "The Improvised Grandpa",
        "The TikTok girl improvises a scene and just grabs Purfluous "
        "because they need a grandpa. He is already on set under a hat "
        "trying to be invisible. Now he is on camera.",
    ),
    StoryBeat(
        "a1_pete_on_camera", 1, "Pete Sees the Girl",
        "The TikTok girl has been trying to get Pete in the movie ever "
        "since she saw her because Pete is hot. This pisses Pete off — "
        "a gorgeous young girl acting like beauty is all that matters.",
    ),

    # ── ACT 2: THE BLOW-UP ───────────────────────────────────────────────
    StoryBeat(
        "a2_fit", 2, "The Fit on Set",
        "The TikTok girl throws a fit because of the shitty script, "
        "bad direction, and zero organization. She storms off set doing "
        "crying selfies. Pete is visible in the background of the "
        "selfie footage.",
        gameplay_hook=(
            "Player must manage the chaos — keep the gear from being "
            "damaged, keep the crew calm, protect the equipment."
        ),
    ),
    StoryBeat(
        "a2_abandoned", 2, "Abandoned Set",
        "The girl leaves. But the next day the rental trucks, extras, "
        "and cast actors still show up. All this expensive gear is just "
        "sitting there. The crew looks at each other: 'So um are we "
        "just gonna toss it? Fuck no.' They keep making the film.",
        gameplay_hook=(
            "Player and RePete now have free rein of professional gear. "
            "No instructions from teachers. Time to use everything "
            "learned in the tutorial."
        ),
    ),
    StoryBeat(
        "a2_heart_to_heart", 2, "The Heart-to-Heart",
        "You were set up to shoot a scripted scene but the girl left. "
        "Instead, Pete and Purfluous have a real moment. You capture "
        "them in silhouette, backlit by golden hour, holding hands. "
        "She rests her head on his shoulder. He gives her a fatherly "
        "kiss on the forehead just as the sun sets. This was never "
        "planned — it just happened while the cameras were hot.",
        gameplay_hook=(
            "Player must achieve several complicated camera and sound "
            "tasks in a hurry with only RePete for help. No instruction. "
            "RePete gives the signal and you have to nail it."
        ),
        emotional_note=(
            "Purfluous's greatest on-camera performance — and he is "
            "facing the wrong way. 'My greatest on-camera performance "
            "and I'm facing the wrong way. Typical.'"
        ),
    ),
    StoryBeat(
        "a2_sincere_performance", 2, "The Level Zero",
        "They need a sincere performance from an old man. Purfluous "
        "cannot NOT go to eleven — until this moment, when he is not "
        "acting. He finally drops to zero. The mask falls because he "
        "thinks nobody is watching. It is the first time the audience "
        "sees the real him.",
    ),

    # ── ACT 3: THE INTERNET ──────────────────────────────────────────────
    StoryBeat(
        "a3_clocked", 3, "Pete Gets Clocked",
        "People clock Pete in the background of the TikTok girl's "
        "crying selfie. Pete's former career comes back. Internet "
        "culture picks up on it. What is old is new again. But this "
        "time people actually want to talk to her — the world changed "
        "and everybody is a whore now. She was just ahead of the game.",
    ),
    StoryBeat(
        "a3_trash_talk", 3, "The Talk-Shit Cycle",
        "People online start trashing Pete and the studio. The TikTok "
        "girl keeps bad-mouthing the studio publicly — how much money "
        "she spent, how it smells, the creepy old porn guy.",
    ),
    StoryBeat(
        "a3_repete_posts", 3, "RePete Flies the Flag",
        "RePete — who is their age and knows social media — uploads "
        "backstage footage against everyone's wishes because he knows "
        "better. He posts the heart-to-heart footage. People get all "
        "the feels seeing Pete and Purfluous come to terms with each "
        "other, backlit by golden hour. The take on the project changes.",
        emotional_note=(
            "People see her as a daughter and a woman who made hard "
            "choices and was punished by the patriarchy for living her "
            "truth. Purfluous comes off as the father who let his "
            "'daughter' perform — and it ruined her life. This is their "
            "heartwarming 'seeing' each other. But they are NOT father "
            "and daughter. He is only ten years older. The public is "
            "hallucinating a family tree."
        ),
    ),
    StoryBeat(
        "a3_scandal", 3, "Poppy Poppin",
        "The good girl hired a porn studio. The headline writes itself: "
        "'Poppy Poppin her P***y.' People think she is auctioning off "
        "her virginity for TikTok. If she does not release something, "
        "people will think she did it but was too scared to release it. "
        "She HAS to release something and it has to center around that "
        "leaked set footage at the heart of it.",
    ),

    # ── ACT 4: THE CRAWL-BACK ────────────────────────────────────────────
    StoryBeat(
        "a4_crawl_back", 4, "The Crawl-Back",
        "The TikTok girl comes crawling back. She is terrified by the "
        "fan drop-off. Her influencer friends are sharing stories that "
        "are mostly not true. She has to reframe everything as viral "
        "marketing: 'I was doing exactly what everyone did to them — "
        "to set it up for the reveal that I AM Pete.' The PR angle.",
    ),
    StoryBeat(
        "a4_mercy", 4, "The Mercy",
        "Pete and Purfluous decide: 'She is 17. Let us not ruin this "
        "girl's career. I know what it is like to be trapped by a past "
        "of questionable movies. Let us see what we can do.' They lean "
        "into the girl's lie — not because they believe it, but because "
        "it is a life raft.",
        emotional_note=(
            "The sappy lesson: you and the others were being as "
            "dismissive of the TikTok girl as people were about porn. "
            "Everyone has a hard life. Everyone has their costume to "
            "bear."
        ),
    ),
    StoryBeat(
        "a4_young_pete", 4, "Young Pete",
        "Now the TikTok girl wants to make Pete's story. She is "
        "playing Young Pete. That is why Pete is her mother in the "
        "film — because the girl wants to hire these people with a "
        "past that people dismiss, and she feels that connection "
        "because she is just some TikTok bitch, right? That was never "
        "the plan — until they tell people it was.",
    ),

    # ── ACT 5: THE PREMIERE ──────────────────────────────────────────────
    StoryBeat(
        "a5_premiere", 5, "The Dirty Palace Premiere",
        "The premiere is in the dirty, dingy, old beat-up movie palace. "
        "A double feature: the TikTok flick, and — unbeknownst to "
        "Pete — the secret doc 'Influencer Under the Influence.' The "
        "audience has never seen a retro film in a real theatre like "
        "this. The dilapidated setting feels authentic. True throwback "
        "filmmaking.",
        gameplay_hook=(
            "Player watches their own work on the big screen. The "
            "tutorial tasks from early in the game reappear as scenes "
            "in the finished film."
        ),
    ),
    StoryBeat(
        "a5_angel_devil", 5, "Angel and Devil",
        "The last shot: Pete is handed the flyer or hears the "
        "announcer. The double feature is 'The Angel and the Devil. "
        "Good Girl. Naughty Girl.' Pete did not know about the double "
        "feature. Purfluous is just tickled — he gets his red carpet "
        "interview.",
        emotional_note=(
            "You cannot hide from your past. Just listen to the band "
            "and dance along."
        ),
    ),

    # ── EPILOGUE: OPEN MODE ──────────────────────────────────────────────
    StoryBeat(
        "epilogue_open", 99, "Start Anything",
        "Studio finances stabilized. The bartender was sneaky and sold "
        "enough merch and 'movie snow' to keep the place running. Open "
        "mode unlocked. Player can start new projects, replay any "
        "discipline, explore, collaborate, or just hang out in the pub "
        "watching the cast unwind. Game done.",
        gameplay_hook=(
            "Brainstorm meetings in the conference room. Dartboard "
            "randomization ceremony for five parameters. Full "
            "production mode. Or just whatever you want."
        ),
    ),
]


# ════════════════════════════════════════════════════════════════════════════
# GAME MODE / PROJECT MODE STRUCTURE
# ════════════════════════════════════════════════════════════════════════════

GAME_MODE_STRUCTURE: Dict[str, str] = {
    "concept": (
        "Game mode trains you for project mode. The whole game is a "
        "tutorial. The game teaches you filmmaking by making you work "
        "on the TikTok girl's terrible movie. Each task is a real "
        "skill disguised as a vapid request."
    ),
    "runtime": (
        "Two to three hours depending on how meticulous you get with "
        "your movie. A big crowd scene and dance number with 30 cues "
        "takes a while. A guy and girl sitting at dinner until one "
        "leaves — much faster."
    ),
    "repeatability": (
        "Totally repeatable. Puzzles and events randomized. Which "
        "lines and sounds trigger when in the foley exercise are "
        "different each time. Your final project is always original. "
        "You can play that level any time with friends."
    ),
    "final_project_genres": (
        "Game show, murder mystery, romance, arthouse, noir, musical, "
        "comedy of errors, documentary, horror, mockumentary. "
        "Purfluous is doing an arthouse piece of literally watching "
        "paint dry and documenting his naps — a Warhol joke."
    ),
    "five_parameters": (
        "Five parameters picked randomly via backward dart throws at "
        "a wall grid. You throw two. Purfluous, Pete, the bartender, "
        "or friends throw the others. Marla sometimes throws one — "
        "she does not want to be bothered, flicks it without looking, "
        "it hits the ground and scares the cat, so you get a free "
        "choice. Graded with points that do not really do anything "
        "except maybe credits toward costumes or models for sale."
    ),
    "parameter_categories": (
        "Genre/format, theme/emotion, required prop or motif, "
        "technical limitation, wildcard/curveball."
    ),
    "environmental_complications": (
        "Sometimes you only have an old western set and a horse that "
        "wandered in from a parade. Sometimes it rained so you have "
        "to shoot indoors at a pet shop with the dog, cat, horse, and "
        "mice. The local coffee shop is dead between breakfast and "
        "lunch so you have two hours with the run of it."
    ),
}

PROJECT_MODE_LOCATIONS: Dict[str, str] = {
    "dressing_room": "Hub. Start here. Mirror, corkboard, wardrobe rack.",
    "pub_world": "Workshop and set building. Scavenge props, fix lights.",
    "control_room": "Technical HQ. Edit video, balance sound, set up lighting grids.",
    "conference_room": "Writing and brainstorming with AI crew.",
    "theater_stage": "Rehearsals. Block scenes, run dialogue, test choreography.",
    "studio_set": "Shooting floor. Frame shots, run camera moves, call action.",
    "foley_room": (
        "Sound effects mini-game. Bang coconuts for horse hooves, stomp "
        "on a wooden floor, switch to heels halfway through, strum a "
        "guitar, set it down without a sound, slam a door, a woman "
        "screams, and a cat meows — Pints's big moment."
    ),
}

MENTOR_SPLIT: Dict[str, str] = {
    "purfluous_teaches": (
        "Avatar dressing, wardrobe, makeup, lighting mood (emotional "
        "not technical), acting, choreography, monologue and emotion. "
        "The old magic. The theatre side. Instinct."
    ),
    "pete_teaches": (
        "Cameras and lenses, control room, lighting board (technical), "
        "editing and post, rendering and distribution. The systems "
        "side. Craft. Precision."
    ),
    "foley_reveal": (
        "After you complete the foley mini-game with coconuts and "
        "stomping, Pete watches for a beat and says: 'Cute. But you "
        "know we have had software for that since 1974, right?' This "
        "is the first full admission that things are not what they "
        "seemed. You notice a hidden computer in an old vacuum tube "
        "TV husk."
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# SNOW DAY ARC — THE CLIMAX EPISODE
# ════════════════════════════════════════════════════════════════════════════

SNOW_DAY_ARC: Dict[str, str] = {
    "setup": (
        "RePete opens a crate looking for decorations and finds old "
        "canisters labeled MOVIE SNOW — DO NOT TASTE. He rigs a snow "
        "machine from leaf-blowers, dryer hoses, and the canisters."
    ),
    "the_blizzard": (
        "Purfluous delivers his closing line. RePete flips the breaker. "
        "Foam, paper flakes, glitter, and soap bubbles explode from "
        "every vent. Pints the cat launches across the stage chasing "
        "flakes. It starts actually snowing outside through the "
        "cracked skylight. Real flakes mix with the fake ones."
    ),
    "it_doesnt_melt": (
        "The movie snow does not melt. Purfluous rubs a flake between "
        "his fingers. It just smears. 'It does not melt. Maybe it "
        "never was snow.'"
    ),
    "three_days_later": (
        "The bar is spotless but the people are wrecks. Purfluous "
        "slumped in a booth in sunglasses. Pete asleep at the bar. "
        "RePete under a table clutching an empty canister. The cat "
        "belly-up."
    ),
    "the_cocaine_joke": (
        "RePete was uncharacteristically proactive the whole episode — "
        "eager to fix EVERYTHING, tightening screws. The police show "
        "up and clear the place out. Purfluous tells you about the "
        "harsh burden of success as if the police were chasing fans "
        "instead of people looking for more free drugs. The snow that "
        "does not melt. The bar that is spotless. The people that are "
        "wrecked. It only ever gets called 'snow' or 'movie snow.'"
    ),
    "resolution": (
        "The bartender was sneaky and sold enough 'souvenirs' that the "
        "studio should be fine for a while. Open mode unlocked."
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# THE SECRET DOCUMENTARY — "INFLUENCER UNDER THE INFLUENCE"
# ════════════════════════════════════════════════════════════════════════════

SECRET_DOC: Dict[str, str] = {
    "title": "Influencer Under the Influence",
    "creator": "RePete",
    "origin": (
        "RePete found a video that fell out of a box the player was "
        "sorting. That video became the anchor. He turned the whole "
        "thing into a secret documentary about the studio."
    ),
    "method": (
        "He weaves the TikTok girl's vapid footage with the grainy "
        "back-of-the-head truth captured during production. He uses "
        "the backstage footage of the girl throwing fits alongside "
        "the heart-to-heart golden hour footage."
    ),
    "impact": (
        "When people online start trashing Pete and the studio, "
        "RePete posts the mini-doc. People get all the feels. The "
        "take on the project changes overnight. Interest in the movie "
        "explodes. 'Who are these people? What are they doing in "
        "there? I got to see it.'"
    ),
    "double_meaning": (
        "The title means both: the girl is under the influence of her "
        "own fame, and the studio is under the influence of her money. "
        "Both are intoxicated. Both are trapped."
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# THE DOUBLE FEATURE PREMIERE
# ════════════════════════════════════════════════════════════════════════════

PREMIERE: Dict[str, str] = {
    "venue": (
        "A dirty, dingy, old beat-up movie palace. Fading gold leaf, "
        "velvet seats that smell like fifty years of dust, a screen "
        "that has seen better days."
    ),
    "feature_one": (
        "The TikTok flick — high-saturated, over-sharpened, loud. "
        "Every scene has a 360-degree camera spin. Pete in ridiculous "
        "melodramatic costumes delivering AI-written lines."
    ),
    "feature_two": (
        "The secret doc or the 'real' film built around the golden "
        "hour footage. True throwback filmmaking. Grain, texture, "
        "weight. Silhouettes against sunset."
    ),
    "the_flyer": (
        "The Angel and the Devil. Good Girl. Naughty Girl. Pete does "
        "not know about the double feature until she hears the "
        "announcer or is handed the flyer."
    ),
    "audience_reaction": (
        "The audience has never seen retro filmmaking in a real "
        "theatre. The dilapidated setting feels authentic. They came "
        "for the cringe of the TikTok movie but stayed for the aches. "
        "The golden hour footage makes a thousand people cry."
    ),
    "purfluous_at_premiere": (
        "Just tickled. He gets his red carpet interview in a mothball "
        "suit. Talking about the male gaze and meta-narratives to "
        "TikTok reporters who would not know a voxel from a vacuum."
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# REPETE'S FOURTH-WALL BREAK
#
# At the end of the game, RePete breaks the fourth wall to talk directly
# to the player about the next step: going out into the real world.
# Each character has a talent. His is computers. He figured it out one
# day when he saw a problem with the code and after a while solved it.
# This is the creator and the team speaking directly to the player.
# ════════════════════════════════════════════════════════════════════════════

FOURTH_WALL_BREAK: Dict[str, str] = {
    "who": "RePete",
    "purpose": (
        "Seriously talk to the player about the next step after "
        "PubCast — going out into the real world. A chance for the "
        "creator and the team to speak directly to them."
    ),
    "talent_theme": (
        "Each character has a talent. RePete's is computers. He "
        "figured it out one day when he saw a problem with the code "
        "and after a while he solved it. That moment of discovery "
        "is the message: find your thing by doing the work, not by "
        "waiting for permission."
    ),
    "meta_awareness": (
        "During the game there are hints that something is weird "
        "about RePete. He is the only one who knows this is a "
        "computer game. He sees through the simulation. He knows "
        "you are the player. He will not tell Pete or Purfluous. "
        "'Look — they are happy. They do not need to know. Why tell "
        "them? And you know what? I am fine too. I have always got "
        "a place to be. I have got people who care about me. And it "
        "is really nice because I got to cheat and look at the code. "
        "See — it really is there. This is not even a question.'"
    ),
    "staging": (
        "After the player's first open-mode project wraps. The foley "
        "room. The player is alone. RePete walks in, sits on a stool, "
        "and looks at the camera — really looks, for the first time "
        "in the entire game. No accent, no bravado, no jokes. Just "
        "a kid who found his thing by accident. The most expensive "
        "silence in the game. Then the lights come back on and you "
        "are in open mode."
    ),
    "speech": (
        "Hey. You have done great work in here, you know? We have "
        "loved seeing you working and thriving here. But make sure "
        "you work out there too. That is something we can never do. "
        "And something that we have to leave entirely to you.\n\n"
        "But we are always here to help.\n\n"
        "All of us here have a talent. I figured mine out one day "
        "when I saw a problem with the code and after a while I just "
        "— figured it out. And look — they are happy. They do not "
        "need to know. Why tell them? I am fine too. I have always "
        "got a place to be. I have got people who care about me. And "
        "it is really nice, because I got to cheat and look at the "
        "code. See — it really is there. This is not even a question.\n\n"
        "The only question is you. What are you going to do?\n\n"
        "You do not have to stay here. And you should not, you know? "
        "It is great working with you, man. But we will always be "
        "here for you. And hey — this place is going to keep growing, "
        "changing, and there is going to be new stuff all the time. "
        "As long as we can keep this show going.\n\n"
        "So come back. Visit.\n\n"
        "But make sure you visit — and do not stay. There is a big "
        "ass world out there. You get to go live in it.\n\n"
        "Tell us about it when you come back."
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def get_story_beats_by_act(act: int) -> List[StoryBeat]:
    """Return all story beats for a given act number."""
    return [b for b in STORY_ARC if b.act == act]


def get_theme(key: str) -> str:
    """Return a theme string by key, or empty string."""
    return THEMES.get(key, "")


def get_character_root(character_id: str) -> Optional[CharacterRoot]:
    """Return the autobiographical root for a character."""
    return CHARACTER_ROOTS.get(character_id)
