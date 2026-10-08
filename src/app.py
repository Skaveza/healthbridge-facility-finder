import os

from flask import Flask, redirect, render_template, request, url_for

from finder import (CARE_SYSTEMS, SERVICES, SUBCOUNTIES, TOTAL, audit_summary, in_uganda,
                    nearby, subcounty_centre)

app = Flask(__name__)
AUDIT = audit_summary()


@app.route("/")
@app.route("/home")
def home():
    return render_template("home.html")

@app.route("/visualization")
def visualization():
    return render_template("visualization.html", a=AUDIT)


@app.route("/find", methods=["GET", "POST"])
def find():
    page = {"subcounties": SUBCOUNTIES, "services": SERVICES, "care_systems": CARE_SYSTEMS,
            "results": None, "error": None, "origin": None, "form": {}, "total": f"{TOTAL:,}"}

    if request.method == "POST":
        form = request.form
        page["form"] = form
        lat = lon = None

        # Use the device location if the browser supplied one, otherwise the typed subcounty
        if form.get("lat") and form.get("lon"):
            try:
                lat, lon = float(form["lat"]), float(form["lon"])
                page["origin"] = "your location"
            except ValueError:
                page["error"] = "We couldn't read your location. Try again or enter a subcounty."
        elif form.get("subcounty", "").strip():
            centre = subcounty_centre(form["subcounty"])
            if centre:
                lat, lon = centre
                page["origin"] = form["subcounty"].strip()
            else:
                page["error"] = "We couldn't find that subcounty. Pick one from the suggestions."
        else:
            page["error"] = "Share your location or enter a subcounty to search."

        if lat is not None and not in_uganda(lat, lon):
            page["error"] = ("This location is outside Uganda, which is the only country this data covers. "
                             "Enter a Ugandan subcounty instead.")
            lat = None

        if lat is not None:
            page["results"] = nearby(lat, lon, form.get("service"), form.get("care_system") or None)

    return render_template("find.html", **page)


# Old pages from the prediction version now send visitors to the finder,
# so any existing links in your templates keep working until you remove them.
@app.route("/predict")
def predict():
    return redirect(url_for("find"))


@app.route("/retrain")
def retrain():
    return redirect(url_for("find"))


if __name__ == "__main__":
    # Turn the debugger on only on your own machine: set FLASK_DEBUG=1
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")