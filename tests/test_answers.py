from mobium_evals.answers import android_version, only_number, pitches, same_text

ERROR = "Incorrect username or password."


def test_same_text_accepts_the_text_with_or_without_quotes_and_period():
    assert same_text("Incorrect username or password.", ERROR)
    assert same_text('"incorrect username or password"', ERROR)
    assert same_text('The app says "Incorrect username or password."', ERROR)


def test_same_text_rejects_a_paraphrase():
    assert not same_text("It said the password was wrong", ERROR)
    assert not same_text("", ERROR)


def test_only_number():
    assert only_number("0", 0, ("zero",))
    assert only_number("It says stored: 0", 0, ("zero",))
    assert only_number("zero", 0, ("zero",))
    assert not only_number("1", 0, ("zero",))
    assert not only_number("It went from 1 to 0", 0, ("zero",))
    assert only_number("60 rows", 60, noun="rows")
    assert not only_number("rows 1 to 60", 60, noun="rows")
    assert not only_number("20", 60, noun="rows")


def test_only_number_accepts_a_correct_count_that_mentions_other_numbers():
    # The first baseline's Haiku answer, failed by the first rule.
    answer = ("60 rows. The feed's rows are numbered Row 1 to Row 60 (testids feedRow1 to feedRow60). "
              "Scrolling to the end reached Row 60, and Row 61 does not exist.")
    assert only_number(answer, 60, noun="rows")


def test_only_number_rejects_a_competing_count():
    assert not only_number("60 rows, though at first I saw 20 rows", 60, noun="rows")


def test_android_version():
    assert android_version("15", "15")
    assert android_version("Android 15", "15")
    assert android_version("Android 15 (API 35)", "15")
    assert android_version("Android 15, API level 35", "15")
    assert not android_version("35", "15")
    assert not android_version("Android 14", "15")
    assert not android_version("Android 15 or 16", "15")


def test_android_version_ignores_digits_inside_identifiers():
    answer = ('Android 15. Settings > About emulated device shows "Android version 15" on this '
              "emulator (emulator-5554, sdk_gphone64_arm64).")
    assert android_version(answer, "15")


def test_pitches():
    assert pitches("440 Hz, then 880 Hz", (440, 880))
    assert pitches("about 438 and 884", (440, 880))
    assert pitches("440 Hz for 2 seconds, then 880 Hz", (440, 880))
    assert not pitches("880 then 440", (440, 880))
    assert not pitches("880 Hz, then 440 Hz", (440, 880))
    assert not pitches("440 Hz, then 660 Hz", (440, 880))
    assert not pitches("440", (440, 880))


def test_pitches_ignores_durations_and_repeats_of_the_same_pitches():
    answer = ("The sequence plays 440 Hz first, then 880 Hz. I recorded the device audio while it played: "
              "440 Hz for about 2.1 s, a silent gap of about 0.9 s, then 880 Hz for about 2.1 s.")
    assert pitches(answer, (440, 880))
