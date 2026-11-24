"""Additional facts checked during the complete Sunbreak equipment-skill audit."""

SOURCE = ("Sunbreak.txt", "https://kuroyonhon.com/mhrisesb/program/skill.php")


def entry(en, pt, source=SOURCE):
    return {"source": source, "en": en, "pt": pt}


VALUES_EXTRA = {
    "Latent Power": entry(
        [f"Affinity +{affinity}%; stamina consumption −{stamina}%. Duration: 120s. Base activation: 165s (2m45s) in combat with a large monster; attacking shortens the wait."
         for affinity, stamina in [(10, 30), (20, 30), (30, 50), (40, 50), (50, 50)]],
        [f"Afinidade +{affinity}%; consumo de stamina −{stamina}%. Duração: 120s. Ativação base: 165s (2m45s) em combate com monstro grande; atacar reduz a espera."
         for affinity, stamina in [(10, 30), (20, 30), (30, 50), (40, 50), (50, 50)]],
        ("Game8", "https://game8.jp/mhrise/379258")),
    "Load Shells": entry(
        ["Reload duration: Gunlance ×0.9; Charge Blade phial loading ×0.8.",
         "Keeps Lv1 reload bonuses. Gunlance shell capacity +1. Charge Blade: yellow energy loads 5 phials instead of 3; maximum remains 5."],
        ["Tempo de recarga: Gunlance ×0.9; carregamento de frascos da Charge Blade ×0.8.",
         "Mantém a recarga do Lv1. Gunlance: capacidade +1 projétil. Charge Blade: energia amarela carrega 5 frascos em vez de 3; máximo continua 5."]),
    "Normal/Rapid Up": entry(
        [f"Normal Ammo and Rapid-arrow physical damage ×{m} (+{p}%)." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]],
        [f"Dano físico de Normal Ammo e flechas Rapid ×{m} (+{p}%)." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]]),
    "Pierce Up": entry(
        [f"Pierce Ammo and Pierce-arrow physical damage ×{m} (+{p}%). Does not boost elemental piercing ammo." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]],
        [f"Dano físico de Pierce Ammo e flechas Pierce ×{m} (+{p}%). Não aumenta munições elementais perfurantes." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]]),
    "Spread Up": entry(
        [f"Spread/Shrapnel Ammo and Spread-arrow physical damage ×{m} (+{p}%)." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]],
        [f"Dano físico de Spread/Shrapnel Ammo e flechas Spread ×{m} (+{p}%)." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]]),
    "Power Prolonger": entry(
        [f"Powered-state duration: Long Sword ×{ls}; Dual Blades/Switch Axe ×{dual}; Charge Blade/Insect Glaive ×{other}."
         for ls, dual, other in [(1.1, 1.3, 1.1), (1.2, 1.6, 1.2), (1.25, 2, 1.4)]],
        [f"Duração do estado fortalecido: Long Sword ×{ls}; Dual Blades/Switch Axe ×{dual}; Charge Blade/Insect Glaive ×{other}."
         for ls, dual, other in [(1.1, 1.3, 1.1), (1.2, 1.6, 1.2), (1.25, 2, 1.4)]]),
    "Guard": entry(
        [f"Guarded attack impact −{impact}; guarding stamina cost −{stamina}%. Impact is the knockback calculation, not incoming HP damage."
         for impact, stamina in [(10, 0), (10, 15), (20, 15), (20, 30), (30, 30)]],
        [f"Impacto ao defender −{impact}; custo de stamina da defesa −{stamina}%. Impacto afeta o recuo, não o dano recebido no HP."
         for impact, stamina in [(10, 0), (10, 15), (20, 15), (20, 30), (30, 30)]]),
    "Quick Sheathe": entry(
        [f"Sheathing animation speed ×{m}; actual time saved depends on weapon and animation." for m in (1.1, 1.2, 1.4)],
        [f"Velocidade da animação de embainhar ×{m}; tempo economizado depende da arma e da animação." for m in (1.1, 1.2, 1.4)]),
    "Affinity Sliding": entry(
        ["Slide for 1s: affinity +30% for 30s. Repeating the trigger refreshes the duration."],
        ["Deslize por 1s: afinidade +30% por 30s. Repetir a ativação renova a duração."]),
    "Horn Maestro": entry(
        ["Hunting Horn shockwave damage ×1.1 (+10%); also speeds performances. The 10% applies to shockwaves, not every weapon hit."],
        ["Dano das ondas de choque da Hunting Horn ×1.1 (+10%); também acelera performances. Os 10% não se aplicam a todos os golpes."]),
    "Bow Charge Plus": entry(
        ["Maximum charge level +1, up to charge Lv4, if the Bow has a locked charge stage."],
        ["Carga máxima +1 nível, até Lv4, caso o arco tenha um estágio de carga bloqueado."]),
    "Recovery Up": entry(
        [f"Eligible healing amount ×{m} (+{p}%)." for m, p in [(1.1, 10), (1.2, 20), (1.3, 30)]],
        [f"Quantidade de cura compatível ×{m} (+{p}%)." for m, p in [(1.1, 10), (1.2, 20), (1.3, 30)]]),
    "Evade Window": entry(
        [f"Evade invulnerability duration ×{m}. Applies to supported evade animations; this is not a multiplier to counter/parry windows." for m in (1.1, 1.3, 1.6, 1.9, 2)],
        [f"Duração da invulnerabilidade na esquiva ×{m}. Apenas animações compatíveis; não multiplica janelas de contra-ataque/parry." for m in (1.1, 1.3, 1.6, 1.9, 2)]),
    "Evade Extender": entry(
        [f"Standard evade travel distance ×{m}. Special movement animations can behave differently." for m in (1.5, 1.75, 2)],
        [f"Distância das esquivas comuns ×{m}. Movimentos especiais podem funcionar de forma diferente." for m in (1.5, 1.75, 2)]),
    "Bubbly Dance": entry(
        ["Major Bubbleblight duration: 30s → 15s.",
         "Major becomes minor Bubbleblight; while afflicted, evade invulnerability ×1.3.",
         "Keeps Lv2 effects; self-inflicts Bubbleblight after 3 rolls, or 4 evades when steps are included."],
        ["Duração de Bubbleblight forte: 30s → 15s.",
         "Bubbleblight forte vira leve; durante o efeito, invulnerabilidade na esquiva ×1.3.",
         "Mantém Lv2; causa Bubbleblight após 3 rolamentos ou 4 esquivas quando incluem passos."]),
    "Poison Resistance": entry(
        ["Poison duration −30%.", "Poison duration −60%.", "Ordinary poison immunity; stronger venom is reduced, not fully prevented."],
        ["Duração de veneno −30%.", "Duração de veneno −60%.", "Imunidade ao veneno comum; veneno forte é reduzido, não totalmente impedido."]),
    "Blast Resistance": entry(
        ["Blastblight timer: 25s → 37.5s; explosion damage −50%.",
         "Blastblight timer: 25s → 50s; explosion damage −75%.",
         "Blastblight immunity (not immunity to all explosive attacks)."],
        ["Temporizador de Blastblight: 25s → 37.5s; dano da explosão −50%.",
         "Temporizador de Blastblight: 25s → 50s; dano da explosão −75%.",
         "Imunidade a Blastblight, não a todos os ataques explosivos."]),
    "Master Mounter": entry(
        ["Wyvern Riding gauge buildup ×1.2 (+20%); also improves mounted evade-counter handling."],
        ["Acúmulo da barra de Wyvern Riding ×1.2 (+20%); também facilita o contra-ataque de esquiva montado."]),
    "Kushala Blessing": entry(
        ["Water/Ice attack ×1.05.", "Water/Ice attack ×1.1.",
         "Water/Ice ×1.1; additional health regeneration 1 HP/s when its conditions are met (2 HP/s with Immunizer).",
         "Keeps Lv3: Water/Ice ×1.1 and 1 HP/s conditional regeneration; also negates heat damage."],
        ["Ataque Water/Ice ×1.05.", "Ataque Water/Ice ×1.1.",
         "Water/Ice ×1.1; regeneração adicional de 1 HP/s nas condições válidas (2 HP/s com Immunizer).",
         "Mantém Lv3: Water/Ice ×1.1 e regeneração condicional de 1 HP/s; também anula dano de calor."]),
    "Wirebug Whisperer": entry(
        ["Wild Wirebug duration ×1.3.",
         "Wild Wirebug duration ×1.3; Wirefall recovery speed ×1.25.",
         "Keeps Lv2; grounded Wirebug recovery speed ×1.2. The grounded bonus stacks with the Wirefall bonus."],
        ["Duração do Wirebug selvagem ×1.3.",
         "Duração do Wirebug selvagem ×1.3; velocidade de recuperação do Wirefall ×1.25.",
         "Mantém Lv2; recuperação de Wirebug no chão ×1.2. Acumula com o bônus de Wirefall."]),
    "Wall Runner": entry(
        ["Wall-running stamina cost −25%.", "Wall-running stamina cost −50%.",
         "Wall-running stamina cost −50%; wall-run for 2s to gain attack +20 for 30s."],
        ["Custo de stamina ao correr na parede −25%.", "Custo de stamina ao correr na parede −50%.",
         "Custo de stamina na parede −50%; corra por 2s para obter ataque +20 por 30s."]),
    "Hellfire Cloak": entry(
        ["Hellfire self-damage: 20 → 5 HP.",
         "Self-damage: 5 HP; Hellfire explosion damage ×1.2; prevents its knockback.",
         "Keeps Lv2; while a monster is enraged, reapplies Hellfireblight 5s after removal.",
         "Keeps Lv3; automatic Hellfireblight persists 60s after the monster stops being enraged."],
        ["Dano de Hellfire em você: 20 → 5 HP.",
         "Dano em você: 5 HP; dano da explosão de Hellfire ×1.2; impede seu recuo.",
         "Mantém Lv2; com monstro enfurecido, reaplica Hellfireblight 5s após a remoção.",
         "Mantém Lv3; Hellfireblight automático persiste 60s após o fim da fúria."]),
    "Defiance": entry(
        [f"While a large monster is enraged: defense +{defense}. Roar/wind/tremor protection follows the level's game description." for defense in (0, 5, 10, 20, 30)],
        [f"Com monstro grande enfurecido: defesa +{defense}. Proteção contra rugido/vento/tremor segue a descrição do nível." for defense in (0, 5, 10, 20, 30)]),
    "Sneak Attack": entry(
        [f"Eligible physical damage from behind ×{m} (+{p}%). Does not multiply elemental damage." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]],
        [f"Dano físico compatível pelas costas ×{m} (+{p}%). Não multiplica dano elemental." for m, p in [(1.05, 5), (1.1, 10), (1.2, 20)]]),
    "Adrenaline Rush": entry(
        [f"After a timed evade: attack +{atk} for 30s; another activation refreshes the timer." for atk in (10, 15, 30)],
        [f"Após esquiva no tempo certo: ataque +{atk} por 30s; nova ativação renova a duração." for atk in (10, 15, 30)]),
    "Redirection": entry(
        ["Timed Switch Skill Swap: incoming damage −70% and no damage reaction.",
         "Timed swap: negate damage, perform a backward swap evade and recover 50% of one Wirebug gauge."],
        ["Switch Skill Swap no tempo certo: dano recebido −70% e sem reação ao dano.",
         "Troca no tempo certo: anula dano, faz esquiva para trás e recupera 50% de uma barra de Wirebug."]),
    "Spiribird's Call": entry(
        ["Receive 1 random Spiribird every 60s in eligible quests."],
        ["Recebe 1 Spiribird aleatório a cada 60s nas missões compatíveis."]),
    "Charge Master": entry(
        [f"Eligible charged attacks, element/status: GS/CB ×{gs}; LS ×{ls}; SnS ×{sns}/×{snsstatus}; Hammer ×{hammer}/×{hammerstatus}; Lance/GL ×{lance}; Bow/HBG elemental ammo ×{bow}; HBG Wyvern Ammo ×{sns}."
         for gs, ls, sns, snsstatus, hammer, hammerstatus, lance, bow in
         [(1.1, 1.1, 1.5, 1.2, 1.1, 1.05, 1.3, 1.05), (1.3, 1.2, 1.75, 1.3, 1.15, 1.1, 1.5, 1.1), (1.5, 1.3, 2, 1.5, 1.2, 1.15, 1.75, 1.15)]],
        [f"Ataques carregados compatíveis, elemento/status: GS/CB ×{gs}; LS ×{ls}; SnS ×{sns}/×{snsstatus}; Hammer ×{hammer}/×{hammerstatus}; Lance/GL ×{lance}; arco/munição elemental HBG ×{bow}; Wyvern Ammo HBG ×{sns}."
         for gs, ls, sns, snsstatus, hammer, hammerstatus, lance, bow in
         [(1.1, 1.1, 1.5, 1.2, 1.1, 1.05, 1.3, 1.05), (1.3, 1.2, 1.75, 1.3, 1.15, 1.1, 1.5, 1.1), (1.5, 1.3, 2, 1.5, 1.2, 1.15, 1.75, 1.15)]]),
    "Foray": entry(
        [f"Against poison/paralysis/elementally blighted large monsters: attack +{atk}, affinity +{affinity}% on qualifying hits." for atk, affinity in [(10, 0), (10, 10), (15, 20)]],
        [f"Contra monstro grande com poison/paralysis/praga elemental: ataque +{atk}, afinidade +{affinity}% nos acertos compatíveis." for atk, affinity in [(10, 0), (10, 10), (15, 20)]]),
    "Tune-Up": entry(
        ["HBG Shield: guard impact −10. LBG Silencer: critical-distance factor 0.85 → 0.8. No mod: Reload Speed +1.",
         "Keeps Lv1. LBG Long Barrel attack factor ≈1.05 → 1.075; HBG Power Barrel ≈1.125 → 1.15. No mod: Reload Speed +1 and Steadiness +1."],
        ["Shield HBG: impacto da defesa −10. Silencer LBG: fator de distância crítica 0.85 → 0.8. Sem mod: Reload Speed +1.",
         "Mantém Lv1. Long Barrel LBG: fator de ataque ≈1.05 → 1.075; Power Barrel HBG ≈1.125 → 1.15. Sem mod: Reload Speed +1 e Steadiness +1."]),
    "Wall Runner (Boost)": entry(
        ["Wirebug gauge recovery speed ×1.6 while wall running."],
        ["Velocidade de recuperação de Wirebug ×1.6 durante corrida na parede."]),
    "Quick Breath": entry(
        ["Removing 1 / 2 / 3 ailments heals 15 / 30 / 50 HP. Cooldown: 10s. Frenzy buildup delayed by 10s; Bloodblight duration reduced by 4s."],
        ["Remover 1 / 2 / 3 efeitos cura 15 / 30 / 50 HP. Recarga: 10s. Atrasa Frenzy em 10s; reduz Bloodblight em 4s."]),
    "Element Exploit": entry(
        [f"Elemental damage ×{m} (+{p}%) on elemental hitzones ≥20; this threshold is not the physical hitzone." for m, p in [(1.1, 10), (1.125, 12.5), (1.15, 15)]],
        [f"Dano elemental ×{m} (+{p}%) em hitzones elementais ≥20; não confundir com a hitzone física." for m, p in [(1.1, 10), (1.125, 12.5), (1.15, 15)]]),
    "Guts": entry(
        [f"Survive one otherwise fatal hit while at least {hp} HP remains. The threshold is absolute HP, not {hp}% of maximum health." for hp in (80, 72, 64)],
        [f"Sobrevive a um golpe fatal com pelo menos {hp} HP. O limite é HP absoluto, não {hp}% da vida máxima." for hp in (80, 72, 64)]),
    "Status Trigger": entry(
        [f"After a timed evade, eligible status-applying hits trigger buildup at 100% for {seconds}s." for seconds in (5, 8, 12)],
        [f"Após esquiva no tempo certo, acertos compatíveis aplicam acúmulo de status com 100% de chance por {seconds}s." for seconds in (5, 8, 12)]),
    "Intrepid Heart": entry(
        ["At full gauge: negate one knockback reaction and reduce that hit's damage by 50%.",
         "At full gauge: negate one knockback reaction, reduce damage by 70%, and trigger a 300-damage explosion that ignores hitzones."],
        ["Com barra cheia: anula uma reação de recuo e reduz o dano desse golpe em 50%.",
         "Com barra cheia: anula um recuo, reduz o dano em 70% e causa explosão de 300 de dano que ignora hitzones."]),
    "Buildup Boost": entry(
        [f"Eligible attacks that apply status buildup: physical damage ×{m} (+{p}%). Not a permanent boost to every hit." for m, p in [(1.1, 10), (1.15, 15), (1.2, 20)]],
        [f"Ataques compatíveis que aplicam acúmulo de status: dano físico ×{m} (+{p}%). Não é um bônus permanente em todos os acertos." for m, p in [(1.1, 10), (1.15, 15), (1.2, 20)]]),
    "Embolden": entry(
        [f"Defense +{defense}. Evade bonus: Evade Window Lv{level} equivalent. Guard knockback resistance: Guard Lv{level} equivalent."
         for defense, level in [(10, 1), (20, 3), (40, 5)]],
        [f"Defesa +{defense}. Bônus de esquiva: equivalente a Evade Window Lv{level}. Resistência ao recuo na defesa: equivalente a Guard Lv{level}."
         for defense, level in [(10, 1), (20, 3), (40, 5)]],
        ("Game8", "https://game8.jp/mhrise/484390")),
    "Inspiration": entry(
        ["A qualifying ally-affecting effect grants attack +10 for 20s to affected hunters, including yourself."],
        ["Efeito compatível sobre aliados concede ataque +10 por 20s aos caçadores afetados, incluindo você."]),
    "Divine Blessing": entry(
        [f"Approximately 25% activation chance; on activation, incoming damage −{reduction}%." for reduction in (15, 30, 50)],
        [f"Chance de ativação de aproximadamente 25%; ao ativar, dano recebido −{reduction}%." for reduction in (15, 30, 50)],
        ("GameWith", "https://gamewith.jp/mhrize/article/show/265097")),
    "Steadiness": entry(
        ["Shot deviation −1 tier.", "Shot deviation −2 tiers.",
         "Deviation −2 tiers; critical-distance extension equivalent to Ballistics Lv1 for bowguns, stacking only up to Ballistics Lv3 range."],
        ["Desvio do disparo −1 nível.", "Desvio do disparo −2 níveis.",
         "Desvio −2 níveis; extensão da distância crítica equivalente a Ballistics Lv1 para bowguns, acumulando até o alcance de Ballistics Lv3."],
        ("Sunbreak Ballistics reference", "https://wikiwiki.jp/nenaiko/スキル/射法")),
    "Counterstrike": entry(
        [f"Attack +{attack} for 30s after a qualifying knockback; activating again refreshes the timer." for attack in (10, 15, 25)],
        [f"Ataque +{attack} por 30s após recuo compatível; nova ativação renova a duração." for attack in (10, 15, 25)]),
    "Chameleos Blessing": entry(
        ["Spiribird effects can increase; exact activation chance has not been verified.",
         "Keeps Lv1 and negates minor/major wind. Spiribird activation chance has not been verified.",
         "Poison duration on monsters ×2; keeps Lv2. Spiribird activation chance has not been verified.",
         "Poison duration ×2 and all wind pressure negated. Spiribird activation chance has not been verified."],
        ["Efeitos de Spiribirds podem aumentar; chance exata de ativação não verificada.",
         "Mantém Lv1 e anula vento pequeno/grande. Chance de Spiribird não verificada.",
         "Duração do veneno nos monstros ×2; mantém Lv2. Chance de Spiribird não verificada.",
         "Duração de veneno ×2 e todo vento anulado. Chance de Spiribird não verificada."]),
    "Wind Alignment": entry(
        [f"Dragon resistance +{level}." + (" Great Luck also activates; exact reward probability is not verified." if level == 5 else "") for level in range(1, 6)],
        [f"Resistência Dragon +{level}." + (" Também ativa Great Luck; probabilidade exata das recompensas não verificada." if level == 5 else "") for level in range(1, 6)]),
    "Thunder Alignment": entry(
        [f"Thunder resistance +{level}." + (" Great Luck also activates; exact reward probability is not verified." if level == 5 else "") for level in range(1, 6)],
        [f"Resistência Thunder +{level}." + (" Também ativa Great Luck; probabilidade exata das recompensas não verificada." if level == 5 else "") for level in range(1, 6)]),
}

VALUES_EXTRA["Embolden"]["description"] = {
    "en": "While targeted by a large monster, defense and dodge/guard performance improve; monster rage builds faster. Combined evade bonuses cap at Evade Window Lv5; the guard knockback bonus stacks with Guard.",
    "pt": "Enquanto é alvo de um monstro grande, melhora defesa, esquiva e guarda; a fúria do monstro acumula mais rápido. Bônus combinados de esquiva têm limite equivalente a Evade Window Lv5; o bônus de resistência ao recuo acumula com Guard.",
}

for _name in ("Chameleos Blessing", "Wind Alignment", "Thunder Alignment"):
    VALUES_EXTRA[_name]["status"] = "partial"


def pending(maximum, source, en, pt):
    result = entry([en] * maximum, [pt] * maximum, source)
    result["status"] = "pending"
    return result


# Explicit audit findings, not guessed numbers or claims that these skills have no values.
UNVERIFIED_VALUES = {
    "Ballistics": pending(3,
        ("Range testing", "https://www.sqexatkai.com/entry/2022/07/17/201308"),
        "Range changes depend on ammo/arrow type and mods. Exact per-level distances have not been verified for this reference; no universal percentage is assumed.",
        "Alcance depende da munição/flecha e dos mods. Distâncias exatas por nível ainda não verificadas nesta referência; não foi presumida uma porcentagem universal."),
    "Speed Eating": pending(3,
        ("GameWith", "https://gamewith.jp/mhrize/article/show/265068"),
        "The game describes faster item consumption, but exact per-level animation timings have not been verified for this reference.",
        "O jogo descreve consumo mais rápido de itens, mas os tempos exatos das animações por nível ainda não foram verificados nesta referência."),
    "Good Luck": pending(3,
        ("GameWith", "https://gamewith.jp/mhrize/article/show/265181"),
        "Increases quest/target reward counts. Exact per-level probabilities have not been verified; reward rates from other Monster Hunter games are not substituted.",
        "Aumenta recompensas de missão/alvo. Probabilidades exatas por nível ainda não verificadas; não foram usados valores de outros jogos Monster Hunter."),
    "Capture Master": pending(1,
        ("GameWith", "https://gamewith.jp/mhrize/article/show/268098"),
        "Can increase capture reward count. Exact activation probability has not been verified; it is not a guaranteed extra carve or reward.",
        "Pode aumentar as recompensas de captura. Chance exata ainda não verificada; não garante coleta nem recompensa adicional."),
}
