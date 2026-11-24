"""Curated numeric supplements to the game's deliberately brief skill text.

These are reference facts, not ranking weights or simulation inputs. Each entry
keeps its source; see docs/SKILL_VALUES.md for scope and verification notes.
Keys are the canonical English game names, independent of the display language.
"""


def entry(source, en, pt):
    return {"source": source, "en": en, "pt": pt}


VALUES = {
    "Ammo Up": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/265095"),
        ["Clip capacity +1: Normal/Pierce/Spread/Shrapnel Lv1 and Tranq Ammo. Only affects ammo supported by the bowgun; capacity caps still apply.",
         "Keeps Lv1 benefits; also +1: Normal/Pierce/Spread/Shrapnel Lv2, Sticky Lv1, Slicing, Poison Lv1, Recover Lv1, Fire/Water/Thunder/Ice ammo and their piercing variants.",
         "Most supported ammo +1, including Dragon/Piercing Dragon and remaining status/support ammo. Normal Lv1/Lv2, Pierce Lv1, Spread Lv1 and Shrapnel Lv1 get +2 total. Wyvern Ammo unchanged; capacity caps still apply."],
        ["Capacidade do pente +1: Normal/Pierce/Spread/Shrapnel Lv1 e Tranq Ammo. Apenas munições aceitas pela bowgun; respeita o limite de capacidade.",
         "Mantém Lv1; também +1: Normal/Pierce/Spread/Shrapnel Lv2, Sticky Lv1, Slicing, Poison Lv1, Recover Lv1, Fire/Water/Thunder/Ice e variantes perfurantes.",
         "Maioria das munições aceitas +1, incluindo Dragon/Piercing Dragon e demais status/suporte. Normal Lv1/Lv2, Pierce Lv1, Spread Lv1 e Shrapnel Lv1 recebem +2 no total. Wyvern Ammo sem aumento; respeita o limite de capacidade."]),
    "Bloodlust": entry(
        ("Sunbreak.txt", "https://kuroyonhon.com/mhrisesb/program/skill.php"),
        [f"Infected: attack +{atk}; element/status +{ele}; fixed stamina cost −{stamina}%; evade invulnerability ×{evade}. Recovery: affinity +{affinity}% for {seconds}s."
         for atk, ele, stamina, evade, affinity, seconds in
         [(10, 5, 10, 1.1, 20, 60), (15, 7, 20, 1.3, 25, 60), (20, 10, 30, 1.6, 25, 90)]],
        [f"Infectado: ataque +{atk}; elemento/status +{ele}; custo fixo de stamina −{stamina}%; invulnerabilidade na esquiva ×{evade}. Recuperação: afinidade +{affinity}% por {seconds}s."
         for atk, ele, stamina, evade, affinity, seconds in
         [(10, 5, 10, 1.1, 20, 60), (15, 7, 20, 1.3, 25, 60), (20, 10, 30, 1.6, 25, 90)]]),
    "Mail of Hellfire": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/350349"),
        [f"Red Scroll: attack +{atk}, defense −{defense}. Blue Scroll: element ×{element}, all elemental resistances −{res}."
         for atk, defense, element, res in [(15, 50, 1.05, 10), (25, 75, 1.1, 25), (35, 100, 1.2, 50)]],
        [f"Pergaminho vermelho: ataque +{atk}, defesa −{defense}. Azul: elemento ×{element}, todas as resistências elementais −{res}."
         for atk, defense, element, res in [(15, 50, 1.05, 10), (25, 75, 1.1, 25), (35, 100, 1.2, 50)]]),
    "Dereliction": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/349065"),
        [f"With 1 / 2 / 3 Qurio — Red Scroll: element +{ele}. Blue Scroll: attack +{atk}."
         for ele, atk in [("5 / 8 / 12", "15 / 20 / 25"), ("7 / 12 / 15", "20 / 25 / 30"), ("10 / 15 / 20", "25 / 30 / 35")]],
        [f"Com 1 / 2 / 3 Qurio — vermelho: elemento +{ele}. Azul: ataque +{atk}."
         for ele, atk in [("5 / 8 / 12", "15 / 20 / 25"), ("7 / 12 / 15", "20 / 25 / 30"), ("10 / 15 / 20", "25 / 30 / 35")]]),
    "Coalescence": entry(
        ("Sunbreak skill research", "https://bozumemo.blogspot.com/2022/07/skill-attribute-MHRS.html"),
        [f"After recovery from a blight/status: attack +{atk}, element +{ele}, status buildup +{status}% for 30s."
         for atk, ele, status in [(12, 2, 5), (15, 3, 10), (18, 4, 15)]],
        [f"Após se recuperar de praga/status: ataque +{atk}, elemento +{ele}, acúmulo de status +{status}% por 30s."
         for atk, ele, status in [(12, 2, 5), (15, 3, 10), (18, 4, 15)]]),
    "Furious": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/349784"),
        [f"Red Scroll: defense +{defense}, all elemental resistances +{res}. At full fury, swap to Blue: no stamina consumption for {seconds}s."
         for defense, res, seconds in [(10, 5, 30), (20, 10, 60), (30, 20, 90)]],
        [f"Vermelho: defesa +{defense}, todas as resistências elementais +{res}. Com fúria cheia, troque para azul: stamina infinita por {seconds}s."
         for defense, res, seconds in [(10, 5, 30), (20, 10, 60), (30, 20, 90)]]),
    "Blood Rite": entry(
        ("Sunbreak datamine", "https://www.reddit.com/r/MonsterHunterMeta/comments/vhyq1g/"),
        [f"Heal from damage to broken parts: melee {melee}%; Light Bowgun/Bow {ranged}%."
         for melee, ranged in [(3, 2), (6, 5), (10, 8)]],
        [f"Cura pelo dano em partes quebradas: corpo a corpo {melee}%; Light Bowgun/arco {ranged}%."
         for melee, ranged in [(3, 2), (6, 5), (10, 8)]]),
    "Burst": entry(
        ("All-weapon tests", "https://a-to-monhan.com/2022/07/04/sukiru-rengeki/"),
        [f"5-hit totals (attack / element): melee except Dual Blades +{atk} / +{ele}; Dual Blades +{atk} / +{dual}; Bow +{ranged} / +{bow}; bowgun attack +{ranged}. Resets after 3s without hits."
         for atk, ele, dual, ranged, bow in [(10, 8, 6, 8, 6), (12, 10, 8, 9, 8), (15, 15, 12, 10, 10)]],
        [f"Totais após 5 acertos (ataque / elemento): corpo a corpo exceto Dual Blades +{atk} / +{ele}; Dual Blades +{atk} / +{dual}; arco +{ranged} / +{bow}; ataque bowgun +{ranged}. Reinicia após 3s sem acertos."
         for atk, ele, dual, ranged, bow in [(10, 8, 6, 8, 6), (12, 10, 8, 9, 8), (15, 15, 12, 10, 10)]]),
    "Strife": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/376787"),
        ["With red health (>0 but below 60% of max): element +5%, affinity +5%. At 60% or more: element +10%, affinity +10%.",
         "With red health (>0 but below 60% of max): element +10%, affinity +10%. At 60% or more: element +15%, affinity +15%.",
         "With red health (>0 but below 60% of max): element +15%, affinity +10%. At 60% or more: element +20%, affinity +20% and no stamina consumption."],
        ["Com vida vermelha (>0 e abaixo de 60% do máximo): elemento +5%, afinidade +5%. A partir de 60%: elemento +10%, afinidade +10%.",
         "Com vida vermelha (>0 e abaixo de 60% do máximo): elemento +10%, afinidade +10%. A partir de 60%: elemento +15%, afinidade +15%.",
         "Com vida vermelha (>0 e abaixo de 60% do máximo): elemento +15%, afinidade +10%. A partir de 60%: elemento +20%, afinidade +20% e stamina infinita."]),
    "Blood Awakening": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/402807"),
        [f"50 → 150 HP from Blood Rite/Bloodblight; 30s per stage. Melee attack/element: {melee}. Bow attack/element: {bow}. Bowgun attack: {gun}."
         for melee, bow, gun in [("+5/+5 → +10/+10", "+4/+4 → +8/+8", "+4 → +8"),
                                 ("+5/+5 → +20/+20", "+4/+4 → +15/+10", "+4 → +15"),
                                 ("+15/+15 → +40/+30", "+10/+8 → +25/+15", "+10 → +25")]],
        [f"50 → 150 HP via Blood Rite/Bloodblight; 30s por estágio. Ataque/elemento corpo a corpo: {melee}. Arco: {bow}. Ataque bowgun: {gun}."
         for melee, bow, gun in [("+5/+5 → +10/+10", "+4/+4 → +8/+8", "+4 → +8"),
                                 ("+5/+5 → +20/+20", "+4/+4 → +15/+10", "+4 → +15"),
                                 ("+15/+15 → +40/+30", "+10/+8 → +25/+15", "+10 → +25")]]),
    "Frenzied Bloodlust": entry(
        ("MHRise Recipe", "https://mhrise.com/data/4105.html"),
        [f"Overcoming Frenzy grants +1 Wirebug for {seconds}s."
         for seconds in (30, 60, 90)],
        [f"Superar Frenzy concede +1 Wirebug por {seconds}s."
         for seconds in (30, 60, 90)]),
    "Grinder (S)": entry(
        ("Sharpness tests", "https://k-k-kohei.com/2022/08/06/mhrsb-skill-grinder_s/"),
        [f"Restore {tiers} sharpness tiers: raw sharpness modifier ×1.1 and elemental sharpness modifier ×1.075 for {seconds}s."
         for tiers, seconds in [(3, 60), (2, 60), (2, 90)]],
        [f"Recupere {tiers} níveis de afiação: multiplicador físico de afiação ×1.1 e elemental ×1.075 por {seconds}s."
         for tiers, seconds in [(3, 60), (2, 60), (2, 90)]]),
    "Bladescale Hone": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/348711"),
        [f"On a successful evade with weapon drawn: {chance}% chance to restore 20 sharpness, refill current bowgun ammo, or boost Bow Close-range Coating damage by about 10% for 30s."
         for chance in (50, 75, 100)],
        [f"Ao esquivar de um ataque com arma em mãos: {chance}% de chance de recuperar 20 de afiação, recarregar a munição atual ou aumentar o dano do Close-range Coating do arco em cerca de 10% por 30s."
         for chance in (50, 75, 100)]),
    "Wind Mantle": entry(
        ("Sunbreak.txt", "https://kuroyonhon.com/mhrisesb/program/skill.php"),
        [f"Wirebug recovery speed, stages 1 → 2 → 3: {stages}. Lasts 15s after the last hit; sheathing ends it."
         for stages in ("×1.05 → ×1.1 → ×1.2", "×1.07 → ×1.15 → ×1.3", "×1.1 → ×1.2 → ×1.4")],
        [f"Velocidade de recuperação do Wirebug, estágios 1 → 2 → 3: {stages}. Dura 15s após o último acerto; embainhar encerra."
         for stages in ("×1.05 → ×1.1 → ×1.2", "×1.07 → ×1.15 → ×1.3", "×1.1 → ×1.2 → ×1.4")]),
    "Powder Mantle": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/376785"),
        [f"Hits to activate: {hits}. Orange:20s → blue:10s."
         for hits in ("GS:13 LS:27 SnS:33 DB:75 Lance:27 GL:30 Hammer:26 HH:30 SA:31 CB:56 IG:34 LBG:296 HBG:101 Bow:150",
                      "GS:10 LS:20 SnS:24 DB:56 Lance:19 GL:22 Hammer:20 HH:23 SA:23 CB:38 IG:24 LBG:232 HBG:76 Bow:116",
                      "GS:6 LS:14 SnS:17 DB:38 Lance:13 GL:15 Hammer:14 HH:15 SA:15 CB:26 IG:16 LBG:150 HBG:51 Bow:79")],
        [f"Acertos para ativar: {hits}. Laranja:20s → azul:10s."
         for hits in ("GS:13 LS:27 SnS:33 DB:75 Lance:27 GL:30 Hammer:26 HH:30 SA:31 CB:56 IG:34 LBG:296 HBG:101 Bow:150",
                      "GS:10 LS:20 SnS:24 DB:56 Lance:19 GL:22 Hammer:20 HH:23 SA:23 CB:38 IG:24 LBG:232 HBG:76 Bow:116",
                      "GS:6 LS:14 SnS:17 DB:38 Lance:13 GL:15 Hammer:14 HH:15 SA:15 CB:26 IG:16 LBG:150 HBG:51 Bow:79")]),
    "Frostcraft": entry(
        ("Sunbreak.txt", "https://kuroyonhon.com/mhrisesb/program/skill.php"),
        [f"Up to {level} gauge stage(s). At the highest available stage — melee ×{melee}; Bow ×{bow}; bowgun ×{gun}; Cluster/Wyvern/Wyvernblast/Countershot ×{special}. Empty gauge: ×1."
         for level, melee, bow, gun, special in [(1, 1.05, 1.05, 1.1, 1.05), (2, 1.2, 1.2, 1.2, 1.1), (3, 1.3, 1.25, 1.25, 1.15)]],
        [f"Até {level} estágio(s) de barra. No maior estágio disponível — corpo a corpo ×{melee}; arco ×{bow}; bowgun ×{gun}; Cluster/Wyvern/Wyvernblast/Countershot ×{special}. Barra vazia: ×1."
         for level, melee, bow, gun, special in [(1, 1.05, 1.05, 1.1, 1.05), (2, 1.2, 1.2, 1.2, 1.1), (3, 1.3, 1.25, 1.25, 1.15)]]),
    "Dragon Conversion": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/386545"),
        [f"Base all-resistance bonus +{base}. Red: convert summed resistances to element at {melee}% (melee) / {ranged}% (ranged); resistances become 0. Blue hit buff: +{blue} all resistances."
         for base, melee, ranged, blue in [(3, 15, 4, 10), (5, 15, 4, 15), (10, 25, 8, 15)]],
        [f"Bônus base em todas as resistências +{base}. Vermelho: converte a soma em elemento a {melee}% (corpo a corpo) / {ranged}% (à distância); resistências ficam em 0. Bônus por acertos no azul: +{blue} em todas as resistências."
         for base, melee, ranged, blue in [(3, 15, 4, 10), (5, 15, 4, 15), (10, 25, 8, 15)]]),
    "Heaven-Sent": entry(
        ("GameWith", "https://gamewith.jp/mhrize/article/show/395777"),
        [f"Activation without knockback: ~{melee}s melee / ~{ranged}s ranged. First damage taken −50%. Swap: restore 50 sharpness and reload ammo.{extra}"
         for melee, ranged, extra in [(30, 60, ""), (15, 30, ""), (15, 30, " No stamina or sharpness consumption.")]],
        [f"Ativa sem ser derrubado: ~{melee}s corpo a corpo / ~{ranged}s à distância. Primeiro dano recebido −50%. Troca: recupera 50 de afiação e recarrega munição.{extra}"
         for melee, ranged, extra in [(30, 60, ""), (15, 30, ""), (15, 30, " Sem consumo de stamina ou afiação.")]]),
    "Berserk": entry(
        ("Sunbreak.txt", "https://kuroyonhon.com/mhrisesb/program/skill.php"),
        [f"Blue Scroll base drain: {drain} HP/s. Hits increase drain; swapping to Red resets it and converts 50% of remaining red health to green. Empty red health causes fainting."
         for drain in (3, 2)],
        [f"Dreno base no azul: {drain} HP/s. Golpes aumentam o dreno; trocar para vermelho o reinicia e converte 50% da vida vermelha restante em verde. Sem vida vermelha, você desmaia."
         for drain in (3, 2)]),
}


from .skill_values_extra import UNVERIFIED_VALUES, VALUES_EXTRA

VALUES.update(VALUES_EXTRA)


def supplement(names: dict, maximum: int, lang: str) -> dict | None:
    values = VALUES.get(names.get("en", "")) or UNVERIFIED_VALUES.get(names.get("en", ""))
    if not values or len(values["en"]) != maximum:
        return None
    language = "pt" if lang in ("pt", "pt-br") else "en"
    return {"levels": values[language], "status": values.get("status", "supplemented"),
            "description": values.get("description", {}).get(language),
            "source": {"name": values["source"][0], "url": values["source"][1]}}
