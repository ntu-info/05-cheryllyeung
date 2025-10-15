# app.py
from flask import Flask, jsonify, abort, send_file
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

_engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("Missing DB_URL (or DATABASE_URL) environment variable.")
    # Normalize old 'postgres://' scheme to 'postgresql://'
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    _engine = create_engine(
        db_url,
        pool_pre_ping=True,
    )
    return _engine

def create_app():
    app = Flask(__name__)

    @app.get("/", endpoint="health")
    def health():
        return "<p>Server working!</p>"

    @app.get("/img", endpoint="show_img")
    def show_img():
        return send_file("amygdala.gif", mimetype="image/gif")

    @app.get("/terms/<term>/studies", endpoint="terms_studies")
    def get_studies_by_term(term):
        return term

    @app.get("/locations/<coords>/studies", endpoint="locations_studies")
    def get_studies_by_coordinates(coords):
        x, y, z = map(int, coords.split("_"))
        return jsonify([x, y, z])

    @app.get("/dissociate/terms/<term_a>/<term_b>", endpoint="dissociate_terms")
    def dissociate_by_terms(term_a, term_b):
        """
        Returns studies that mention term_a but NOT term_b.
        """
        try:
            eng = get_engine()
            with eng.begin() as conn:
                conn.execute(text("SET search_path TO ns, public;"))

                query = text("""
                    SELECT DISTINCT study_id
                    FROM ns.annotations_terms
                    WHERE term = :term_a
                      AND study_id NOT IN (
                          SELECT study_id
                          FROM ns.annotations_terms
                          WHERE term = :term_b
                      )
                    ORDER BY study_id;
                """)

                result = conn.execute(query, {"term_a": term_a, "term_b": term_b})
                studies = [row[0] for row in result]

                return jsonify({
                    "term_a": term_a,
                    "term_b": term_b,
                    "description": f"Studies mentioning '{term_a}' but not '{term_b}'",
                    "count": len(studies),
                    "studies": studies
                }), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/dissociate/locations/<loc_a>/<loc_b>", endpoint="dissociate_locations")
    def dissociate_by_locations(loc_a, loc_b):
        """
        Returns studies that mention location loc_a (x_y_z) but NOT location loc_b.
        """
        try:
            x1, y1, z1 = map(float, loc_a.split("_"))
            x2, y2, z2 = map(float, loc_b.split("_"))

            eng = get_engine()
            with eng.begin() as conn:
                conn.execute(text("SET search_path TO ns, public;"))

                query = text("""
                    SELECT DISTINCT study_id
                    FROM ns.coordinates
                    WHERE ST_X(geom) = :x1
                      AND ST_Y(geom) = :y1
                      AND ST_Z(geom) = :z1
                      AND study_id NOT IN (
                          SELECT study_id
                          FROM ns.coordinates
                          WHERE ST_X(geom) = :x2
                            AND ST_Y(geom) = :y2
                            AND ST_Z(geom) = :z2
                      )
                    ORDER BY study_id;
                """)

                result = conn.execute(query, {
                    "x1": x1, "y1": y1, "z1": z1,
                    "x2": x2, "y2": y2, "z2": z2
                })
                studies = [row[0] for row in result]

                return jsonify({
                    "location_a": f"{x1}_{y1}_{z1}",
                    "location_b": f"{x2}_{y2}_{z2}",
                    "description": f"Studies with coordinate [{x1}, {y1}, {z1}] but not [{x2}, {y2}, {z2}]",
                    "count": len(studies),
                    "studies": studies
                }), 200

        except ValueError as ve:
            return jsonify({"error": f"Invalid coordinate format: {str(ve)}"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/test_db", endpoint="test_db")
    
    def test_db():
        eng = get_engine()
        payload = {"ok": False, "dialect": eng.dialect.name}

        try:
            with eng.begin() as conn:
                # Ensure we are in the correct schema
                conn.execute(text("SET search_path TO ns, public;"))
                payload["version"] = conn.exec_driver_sql("SELECT version()").scalar()

                # Counts
                payload["coordinates_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.coordinates")).scalar()
                payload["metadata_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.metadata")).scalar()
                payload["annotations_terms_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.annotations_terms")).scalar()

                # Samples
                try:
                    rows = conn.execute(text(
                        "SELECT study_id, ST_X(geom) AS x, ST_Y(geom) AS y, ST_Z(geom) AS z FROM ns.coordinates LIMIT 3"
                    )).mappings().all()
                    payload["coordinates_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["coordinates_sample"] = []

                try:
                    # Select a few columns if they exist; otherwise select a generic subset
                    rows = conn.execute(text("SELECT * FROM ns.metadata LIMIT 3")).mappings().all()
                    payload["metadata_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["metadata_sample"] = []

                try:
                    rows = conn.execute(text(
                        "SELECT study_id, contrast_id, term, weight FROM ns.annotations_terms LIMIT 3"
                    )).mappings().all()
                    payload["annotations_terms_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["annotations_terms_sample"] = []

            payload["ok"] = True
            return jsonify(payload), 200

        except Exception as e:
            payload["error"] = str(e)
            return jsonify(payload), 500

    return app

# WSGI entry point (no __main__)
app = create_app()
