from app.nlu import confirms_send, extract_facts, extract_profile_field, parse_money, refuses_send, yes_no

KAMLA = (
    "मेरा नाम कमला देवी है, मैं 58 साल की विधवा हूँ, रायबरेली के गाँव में रहती हूँ। BPL कार्ड है। "
    "बेटे के पास 1.2 एकड़ ज़मीन है और पोती 6 साल की है। सालाना कमाई 40 हज़ार है"
)


def values(text, expected=None):
    return {k: v[0] for k, v in extract_facts(text, expected).items()}


def test_free_form_hindi_introduction():
    facts = values(KAMLA)
    assert facts["name"] == "कमला देवी"
    assert facts["age"] == 58
    assert facts["is_widow"] is True and facts["gender"] == "female"
    assert facts["district"] == "Raebareli" and facts["state_up"] is True
    assert facts["area"] == "rural"
    assert facts["bpl_card"] is True
    assert facts["owns_farmland"] is True and facts["land_acres"] == 1.2
    assert facts["youngest_girl_age"] == 6 and facts["girl_children_count"] == 1
    assert facts["annual_income"] == 40000


def test_romanised_hindi():
    facts = values("Main 62 saal ka purush hoon, Lucknow se. BPL card nahi hai, gas hai, khata hai")
    assert facts["age"] == 62 and facts["gender"] == "male" and facts["state_up"] is True
    assert facts["bpl_card"] is False and facts["has_lpg"] is True and facts["has_bank_account"] is True


def test_son_age_is_not_applicant_age():
    assert "age" not in values("मेरा बेटा 30 साल का है")


def test_short_answers_use_the_question_just_asked():
    assert values("नहीं", "has_lpg") == {"has_lpg": False}
    assert values("हाँ है", "bpl_card")["bpl_card"] is True
    assert values("58", "age")["age"] == 58
    assert values("अट्ठावन", "age")["age"] == 58
    assert values("५८", "age")["age"] == 58
    assert values("दो", "girl_children_count")["girl_children_count"] == 2
    assert values("नहीं", "girl_children_count")["girl_children_count"] == 0
    assert values("पता नहीं", "bpl_card") == {}


def test_money():
    assert parse_money("40 हज़ार") == 40000
    assert parse_money("डेढ़ लाख") == 150000
    assert parse_money("5 हजार महीना") == 60000
    assert parse_money("dhai lakh") == 250000
    assert parse_money("तीन लाख") == 300000


def test_negated_statements():
    assert values("घर में गैस नहीं है")["has_lpg"] is False
    assert values("ज़मीन नहीं है")["owns_farmland"] is False
    assert values("घर कच्चा है")["has_pucca_house"] is False
    assert values("आय प्रमाण पत्र नहीं है")["doc_income_certificate"] is False
    assert values("आय प्रमाण पत्र बन गया है")["doc_income_certificate"] is True


def test_income_certificate_is_not_income():
    assert "annual_income" not in values("आय प्रमाण पत्र है")


def test_submission_needs_an_explicit_send():
    assert confirms_send("हाँ, भेज दो")
    assert confirms_send("haan bhej do")
    assert not confirms_send("हाँ")
    assert not confirms_send("मत भेजो")
    assert not confirms_send("mat bhejo")
    assert not confirms_send("नहीं भेजना")
    assert refuses_send("रुको, मत भेजो")


def test_yes_no():
    assert yes_no("हाँ") is True
    assert yes_no("नहीं") is False
    assert yes_no("पता नहीं") is None


def test_profile_fields_read_spoken_digits():
    assert extract_profile_field("mobile", "98 76 54 32 10") == "9876543210"
    assert extract_profile_field("aadhaar_last4", "४८२१") == "4821"
    assert extract_profile_field("ifsc", "sbin 0001234") == "SBIN0001234"
    assert extract_profile_field("dob", "15/3/1968") == "15/03/1968"
    assert extract_profile_field("bank_account", "12345") is None


ENGLISH_INTRO = (
    "My name is Kamla Devi, I am a 58 year old widow, I live in a village in Raebareli. I have a BPL card. "
    "My son has 1.2 acres of land and my granddaughter is 6 years old. Our yearly income is 40 thousand."
)


def test_free_form_english_introduction():
    facts = values(ENGLISH_INTRO)
    assert facts["name"] == "Kamla Devi"
    assert facts["age"] == 58
    assert facts["is_widow"] is True and facts["gender"] == "female"
    assert facts["district"] == "Raebareli" and facts["state_up"] is True
    assert facts["area"] == "rural"
    assert facts["bpl_card"] is True
    assert facts["land_acres"] == 1.2 and facts["owns_farmland"] is True
    assert facts["youngest_girl_age"] == 6 and facts["girl_children_count"] == 1
    assert facts["annual_income"] == 40000


def test_english_number_words():
    assert values("fifty eight", "age")["age"] == 58
    assert values("I am fifty eight years old")["age"] == 58
    assert values("two daughters")["girl_children_count"] == 2
    assert values("forty thousand", "annual_income")["annual_income"] == 40000


def test_english_short_answers_and_negation():
    assert values("No", "has_lpg") == {"has_lpg": False}
    assert values("Yes", "bpl_card")["bpl_card"] is True
    assert values("Don't know", "bpl_card") == {}
    assert values("We have no gas connection")["has_lpg"] is False
    assert values("I am a woman")["gender"] == "female"
    assert values("I am a man")["gender"] == "male"


def test_the_word_up_is_only_a_state_when_it_means_one():
    assert "state_up" not in values("I grew up on a farm")
    assert values("I live in UP")["state_up"] is True
    assert values("UP se hoon")["state_up"] is True


def test_english_send_confirmation():
    assert confirms_send("Yes, send it")
    assert not confirms_send("Yes")
    assert not confirms_send("Do not send")
    assert refuses_send("Do not send")


def test_numbers_written_with_commas_stay_whole():
    # Speech engines write "40 thousand" as "40,000", and Indian grouping as "1,20,000".
    assert values("Our yearly income is 40,000 rupees.")["annual_income"] == 40000
    assert values("Income is 1,20,000")["annual_income"] == 120000
    assert values("My income is Rs. 40000")["annual_income"] == 40000
    assert values("I am 58, my income is 3,000 a month")["annual_income"] == 36000
    facts = values("My income is 40,000. I have a BPL card")
    assert facts["annual_income"] == 40000 and facts["bpl_card"] is True


def test_raebareli_in_its_common_spellings():
    for said in ("Raebareli", "Rae Bareli", "Rai Bareli", "Raibareli", "Raybareli"):
        assert values(f"I live in {said}")["district"] == "Raebareli", said
