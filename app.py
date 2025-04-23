import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon
import folium
from streamlit_folium import st_folium
import zipfile
import os
import tempfile

st.set_page_config(page_title="🧭 Contrôle Qualité Cadastral", layout="wide")

lang = st.selectbox("🌐 Choisir une langue / Choose a language", ["Français", "English"])

texts = {
    "Français": {
        "title": "🧭 Contrôle Qualité de Shapefile Cadastral",
        "upload": "📂 Importer un fichier ZIP contenant un shapefile",
        "error_shp": "Aucun fichier .shp trouvé dans l'archive.",
        "summary": "📊 Synthèse des erreurs détectées",
        "map": "🗺️ Carte des superpositions détectées",
        "download": "📥 Télécharger les rapports",
        "excel_button": "📤 Télécharger Excel"
    },
    "English": {
        "title": "🧭 Cadastral Shapefile Quality Check",
        "upload": "📂 Upload a ZIP file containing the shapefile",
        "error_shp": "No .shp file found in the archive.",
        "summary": "📊 Summary of detected errors",
        "map": "🗺️ Map of detected overlaps",
        "download": "📥 Download reports",
        "excel_button": "📤 Download Excel"
    }
}

txt = texts[lang]

st.title(txt["title"])
uploaded_file = st.file_uploader(txt["upload"], type="zip")

if uploaded_file:
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "uploaded.zip")
        with open(zip_path, "wb") as f:
            f.write(uploaded_file.read())
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(tmpdir)

        shp_files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.endswith(".shp")]
        if not shp_files:
            st.error(txt["error_shp"])
        else:
            shapefile_path = shp_files[0]
            df = gpd.read_file(shapefile_path)
            crs = df.crs

            for field in ["Date_enq", "Date_naiss", "Date_deliv", "Dat_delivX", "Dat_trans1", "Dat_trans2"]:
                if field in df.columns:
                    df[field] = pd.to_datetime(df[field], errors="coerce")

            df_valid = df[df["Num_piece"].notna() & ~df["Num_piece"].isin(["Neant", "Néant", "CNI perdu"])]
            df_doublons = df_valid[df_valid["Num_piece"].duplicated(keep=False)]
            df_len_err = df_valid[df_valid["Num_piece"].str.len().fillna(0).astype(int).between(13, 15) == False]
            df_empty = df[df["Nom"].isna() | df["Prenom"].isna() | df["Nat"].isna() | df["Lieu_naiss"].isna()]
            df_incoh = df_valid.groupby("Num_piece").filter(lambda x: x[["Nom", "Prenom"]].nunique().sum() > 2)

            overlaps = []
            for i, a in df.iterrows():
                for j, b in df.iloc[i+1:].iterrows():
                    if a.geometry.intersects(b.geometry):
                        inter = a.geometry.intersection(b.geometry)
                        if inter.geom_type == 'Polygon' and inter.area > 0.1:
                            overlaps.append({
                                "parcelle_1": a.get("Num_parcel", i),
                                "parcelle_2": b.get("Num_parcel", j),
                                "area_m2": inter.area,
                                "geom": inter
                            })
            df_overlaps = gpd.GeoDataFrame(overlaps, geometry="geom", crs=crs)

            summary = pd.DataFrame({
                "Anomalie" if lang == "Français" else "Issue": [
                    "Doublons Num_piece" if lang == "Français" else "Duplicate ID",
                    "Longueur Num_piece invalide" if lang == "Français" else "Invalid ID length",
                    "Superpositions géométriques" if lang == "Français" else "Geometric overlaps",
                    "Champs critiques vides" if lang == "Français" else "Missing critical fields",
                    "Noms incohérents" if lang == "Français" else "Conflicting names"
                ],
                "Nombre" if lang == "Français" else "Count": [
                    len(df_doublons), len(df_len_err), len(df_overlaps), len(df_empty), len(df_incoh)
                ]
            })

            st.subheader(txt["summary"])
            st.dataframe(summary)

            if not df_overlaps.empty:
                m = folium.Map(location=[
                    df_overlaps.geometry.centroid.y.mean(),
                    df_overlaps.geometry.centroid.x.mean()], zoom_start=13)
                for _, row in df_overlaps.iterrows():
                    geo_json = gpd.GeoSeries(row["geom"]).simplify(0.001).to_json()
                    folium.GeoJson(data=geo_json, style_function=lambda x: {"color": "red"}).add_to(m)
                st.subheader(txt["map"])
                st_folium(m, width=1000, height=500)

            if st.button(txt["download"]):
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp_xls:
                    with pd.ExcelWriter(tmp_xls.name, engine="xlsxwriter") as writer:
                        summary.to_excel(writer, sheet_name="Synthèse", index=False)
                        df_doublons.to_excel(writer, sheet_name="Doublons", index=False)
                        df_len_err.to_excel(writer, sheet_name="Longueur", index=False)
                        df_empty.to_excel(writer, sheet_name="Champs_vides", index=False)
                        df_incoh.to_excel(writer, sheet_name="Incohérences", index=False)
                        df_overlaps.drop(columns="geom").to_excel(writer, sheet_name="Superpositions", index=False)
                    st.download_button(txt["excel_button"], tmp_xls.read(), file_name="rapport_qualite.xlsx")
