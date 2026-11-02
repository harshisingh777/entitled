"""25 households labelled by hand from the scheme rules, independently of the engine's output.

Anything not listed under eligible or near_miss must come back not_eligible.
"""

BASE = {
    "state_up": True, "area": "rural", "bpl_card": False, "annual_income": 100000, "owns_farmland": False,
    "income_tax_payer": False, "govt_employee": False, "girl_children_count": 0, "has_lpg": True, "has_pucca_house": True,
    "pregnant_or_lactating": False, "traditional_artisan": False, "has_bank_account": True, "student_class_9plus": False,
    "doc_income_certificate": True, "is_widow": False,
}


def case(label, facts, eligible=(), near_miss=()):
    return {"label": label, "facts": {**BASE, **facts}, "eligible": set(eligible), "near_miss": set(near_miss)}


HOUSEHOLDS = [
    case("Kamla Devi, the demo persona",
         {"age": 58, "gender": "female", "is_widow": True, "bpl_card": True, "annual_income": 40000, "owns_farmland": True,
          "girl_children_count": 1, "youngest_girl_age": 6, "has_lpg": False, "has_pucca_house": False, "doc_income_certificate": False},
         ["pm_kisan", "pm_ujjwala", "ab_pmjay", "pmay_g", "ssy", "pmsby", "nsap_widow", "up_nirashrit_mahila"],
         ["nsap_oldage", "up_vridhavastha", "up_kanya_sumangala"]),
    case("Young farmer", {"age": 30, "gender": "male", "annual_income": 120000, "owns_farmland": True},
         ["pm_kisan", "pmjjby", "pmsby", "apy"]),
    case("BPL man, 62", {"age": 62, "gender": "male", "bpl_card": True, "annual_income": 30000},
         ["ab_pmjay", "pmsby", "nsap_oldage", "up_vridhavastha"]),
    case("Pregnant BPL woman, 25", {"age": 25, "gender": "female", "bpl_card": True, "annual_income": 60000, "has_lpg": False, "pregnant_or_lactating": True},
         ["pm_ujjwala", "ab_pmjay", "pmmvy", "pmjjby", "pmsby", "apy"]),
    case("Student, 17, too young for insurance", {"age": 17, "gender": "female", "student_class_9plus": True},
         ["up_scholarship"]),
    case("Government employee with land", {"age": 45, "gender": "male", "govt_employee": True, "income_tax_payer": True, "annual_income": 800000, "owns_farmland": True, "has_pucca_house": False},
         ["pmjjby", "pmsby"]),
    case("Widow outside UP, 50", {"age": 50, "gender": "female", "is_widow": True, "state_up": False, "bpl_card": True, "annual_income": 50000},
         ["ab_pmjay", "pmjjby", "pmsby", "nsap_widow"]),
    case("Urban man, 61, under the urban limit", {"age": 61, "gender": "male", "area": "urban", "annual_income": 50000},
         ["pmsby", "up_vridhavastha"]),
    case("Rural man, 61, over the rural limit", {"age": 61, "gender": "male", "annual_income": 50000},
         ["pmsby"]),
    case("BPL man, 56, four years from pension", {"age": 56, "gender": "male", "bpl_card": True, "annual_income": 40000},
         ["ab_pmjay", "pmsby"], ["nsap_oldage", "up_vridhavastha"]),
    case("BPL man, 54, outside the near-miss window", {"age": 54, "gender": "male", "bpl_card": True, "annual_income": 40000},
         ["ab_pmjay", "pmsby"]),
    case("Widow, 71, no BPL card", {"age": 71, "gender": "female", "is_widow": True, "annual_income": 30000},
         ["ab_pmjay", "up_vridhavastha", "up_nirashrit_mahila"]),
    case("Man, 30, no bank account", {"age": 30, "gender": "male", "has_bank_account": False},
         [], ["pmjjby", "pmsby", "apy"]),
    case("Man, 45, no bank account", {"age": 45, "gender": "male", "has_bank_account": False},
         [], ["pmjjby", "pmsby"]),
    case("Three daughters", {"age": 35, "gender": "male", "girl_children_count": 3, "youngest_girl_age": 5, "annual_income": 80000},
         ["ssy", "pmjjby", "pmsby", "apy"]),
    case("Two daughters, youngest 12", {"age": 40, "gender": "male", "girl_children_count": 2, "youngest_girl_age": 12, "annual_income": 250000},
         ["up_kanya_sumangala", "pmjjby", "pmsby", "apy"]),
    case("Daughter 8, income over cap and no certificate", {"age": 36, "gender": "female", "girl_children_count": 1, "youngest_girl_age": 8, "annual_income": 350000, "doc_income_certificate": False},
         ["ssy", "pmjjby", "pmsby", "apy"]),
    case("Grown daughter, 20", {"age": 48, "gender": "male", "girl_children_count": 1, "youngest_girl_age": 20},
         ["pmjjby", "pmsby"]),
    case("Urban blacksmith with kutcha house", {"age": 33, "gender": "male", "area": "urban", "traditional_artisan": True, "has_pucca_house": False},
         ["pm_vishwakarma", "pmjjby", "pmsby", "apy"]),
    case("Artisan who is a government employee", {"age": 33, "gender": "male", "traditional_artisan": True, "govt_employee": True},
         ["pmjjby", "pmsby", "apy"]),
    case("Student at home, income under cap", {"age": 44, "gender": "female", "student_class_9plus": True, "annual_income": 190000},
         ["up_scholarship", "pmjjby", "pmsby"]),
    case("Student at home, income over cap", {"age": 44, "gender": "female", "student_class_9plus": True, "annual_income": 210000},
         ["pmjjby", "pmsby"]),
    case("Income-tax payer with land", {"age": 35, "gender": "male", "income_tax_payer": True, "annual_income": 900000, "owns_farmland": True},
         ["pmjjby", "pmsby"]),
    case("Lactating woman, 18", {"age": 18, "gender": "female", "pregnant_or_lactating": True, "bpl_card": True, "has_lpg": False},
         ["pm_ujjwala", "ab_pmjay", "pmjjby", "pmsby", "apy"]),
    case("Young widow, 30, no BPL card", {"age": 30, "gender": "female", "is_widow": True, "annual_income": 150000},
         ["up_nirashrit_mahila", "pmjjby", "pmsby", "apy"]),
]
