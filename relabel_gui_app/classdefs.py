"""classdefs.py — the class taxonomy for the dropdown.

The GUI PREFERS the options embedded in the opened project's JSON
(_via_attributes.region.class.options). `CLASSES` below is only a fallback for a JSON that declares
none. Keep it in sync with the dataset tools' 16-class descriptive taxonomy (core/classes.py).
"""

CLASSES = ["1_Bike", "2_PASSENGER CAR", "3_PICKUP TRUCK", "4_BUS",
           "5_TWO AXLE, SIX TYRES, SINGLE UNIT", "6_THREE AXLE SINGLE UNIT",
           "7_FOUR OR MORE AXLE SINGLE UNIT", "8_FOUR OR LESS AXLE SINGLE TRAILER",
           "9_FIVE AXLE TRACTOR, SEMI TRAILER", "10_6 OR MORE AXLE, SINGLE TRAILER",
           "11_5 OR LESS AXLE, MULTI TRAILER", "12_6 AXLE, MULTI TRAILER",
           "13_7 OR MORE AXLE, MULTI TRAILER", "14_PEDESTRIAN", "15_PEDESTRIAN,CYCLE", "16_WHEEL"]


def class_options_of(via):
    """The class dropdown options declared in a VIA project's _via_attributes (list of labels), or []."""
    try:
        opts = via["_via_attributes"]["region"]["class"]["options"]
        # VIA options is {key: label}; the label (value) is what we show/store. Preserve order.
        return [str(v) if v not in (None, "") else str(k) for k, v in opts.items()]
    except Exception:
        return []
