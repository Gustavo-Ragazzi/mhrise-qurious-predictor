# Numeric skill reference

The game messages often describe effects without numbers. `skill_values.py` supplies
hand-written numeric callouts alongside the original messages. These are reference
facts, never inputs to augment predictions, set searches or ranking scores.

The supplements load at request time and work with existing version-10 caches.
English game names identify skills even when the display language changes. English
and Portuguese callouts are available; other languages fall back to English. If a
skill's maximum level differs from the reference, its supplement is omitted.

## Coverage and references

The [complete audit](SKILL_AUDIT.md) reviews all 147 equipment skills individually.
It records 64 numeric supplements (3 still partial), 68 skills whose main quantities
are already in the game text, 11 categorical effects and 4 references still awaiting
numeric verification. The table below lists the initial supplements; the audit has
the full current roster and sources. Use **Missing / partial values** in the app to
see the seven incomplete references.

Checked on 2026-11-24 against Sunbreak references; not a copy of the demo skill table.

| Skill | Included numbers | Reference |
| --- | --- | --- |
| Ammo Up | Clip increases by ammo type, +2 totals and Wyvern exception | [GameWith](https://gamewith.jp/mhrize/article/show/265095) |
| Bloodlust | Infected bonuses, recovery affinity and duration | [Sunbreak.txt](https://kuroyonhon.com/mhrisesb/program/skill.php) |
| Mail of Hellfire | Red attack/defense, Blue element/resistances | [GameWith](https://gamewith.jp/mhrize/article/show/350349) |
| Dereliction | Attack and element at 1/2/3 Qurio | [GameWith](https://gamewith.jp/mhrize/article/show/349065) |
| Coalescence | Attack, element, status and duration | [Skill research](https://bozumemo.blogspot.com/2022/07/skill-attribute-MHRS.html) |
| Furious | Defense, resistances, infinite-stamina duration | [GameWith](https://gamewith.jp/mhrize/article/show/349784) |
| Blood Rite | Healing ratios | [Datamine](https://www.reddit.com/r/MonsterHunterMeta/comments/vhyq1g/) |
| Burst | Five-hit totals by weapon group and reset time | [Weapon tests](https://a-to-monhan.com/2022/07/04/sukiru-rengeki/), [GameWith cross-check](https://gamewith.jp/mhrize/article/show/348712) |
| Strife | Low/high red-health bonuses | [GameWith](https://gamewith.jp/mhrize/article/show/376787) |
| Blood Awakening | Stage thresholds/duration and melee/Bow/bowgun bonuses | [GameWith](https://gamewith.jp/mhrize/article/show/402807) |
| Frenzied Bloodlust | Extra Wirebug duration | [MHRise Recipe](https://mhrise.com/data/4105.html) |
| Grinder (S) | Sharpness modifiers, trigger tiers and duration | [Sharpness tests](https://k-k-kohei.com/2022/08/06/mhrsb-skill-grinder_s/) |
| Bladescale Hone | Trigger chances, sharpness, ammo and coating effect | [GameWith](https://gamewith.jp/mhrize/article/show/348711) |
| Wind Mantle | Recovery-speed stages and duration | [Sunbreak.txt](https://kuroyonhon.com/mhrisesb/program/skill.php) |
| Powder Mantle | Activation hit counts for all weapons and color timings | [GameWith](https://gamewith.jp/mhrize/article/show/376785) |
| Frostcraft | Highest available gauge-stage multiplier by weapon/ammo | [Sunbreak.txt](https://kuroyonhon.com/mhrisesb/program/skill.php) |
| Dragon Conversion | Base resistances, conversion ratios and Blue buff | [GameWith](https://gamewith.jp/mhrize/article/show/386545) |
| Heaven-Sent | Activation times, damage reduction and sharpness recovery | [GameWith](https://gamewith.jp/mhrize/article/show/395777) |
| Berserk | Base drain and health conversion on swapping | [Sunbreak.txt](https://kuroyonhon.com/mhrisesb/program/skill.php) |

These callouts cover the reviewed level effects, not every hidden mechanic.
Skills without a supplement retain their game descriptions. In particular, do not
infer bowgun elemental values from Bow values, or use a fully charged Frostcraft
bonus after its gauge has fallen. Burst numbers are total bonuses, not additions
on top of the initial hit bonus. Existing game text remains visible for conditions
not repeated in the callouts.

Regression checks distinguish the final game's Mail of Hellfire attack bonuses
(15/25/35) from early demo references, Dereliction's level-2 elemental sequence
(7/12/15), and Burst's separate Dual Blades and ranged results.
