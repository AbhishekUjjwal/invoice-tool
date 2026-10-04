import streamlit as st
import pandas as pd
import pymupdf as fitz
import re
import io
import barcode
from barcode.writer import ImageWriter

st.set_page_config(
    page_title="Amazon Invoice Barcode & Tracking Stamper",
    page_icon="📦",
    layout="centered"
)

st.title("📦 Amazon Invoice Barcode & Tracking Stamper")
st.write("Shipment Report aur Invoice PDF upload karein. **PAN: AALCR5906L Filter + Guaranteed Tracking Stamp** apply hoga.")

# Target PAN jisko filter karke rakhna hai
TARGET_PAN = "aalcr5906l"

# File Uploaders
uploaded_csv = st.file_uploader("1. Upload Shipment Report (CSV / Excel)", type=["csv", "xlsx", "xls"])
uploaded_pdf = st.file_uploader("2. Upload Invoice PDF", type=["pdf"])

def clean_val(v):
    if pd.isna(v):
        return ""
    s = str(v).strip()
    s = re.sub(r'^[="\']+|["\']+$', '', s)
    return s.strip()

def clean_alphanumeric(text):
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()

def generate_barcode_image(code_text):
    """Clean & Crisp Code128 Barcode"""
    try:
        code128 = barcode.get_barcode_class('code128')
        writer = ImageWriter()
        writer.font_path = None
        barcode_instance = code128(code_text, writer=writer)
        
        buffer = io.BytesIO()
        barcode_instance.write(
            buffer,
            options={
                'write_text': False,
                'module_width': 0.45,
                'module_height': 15.0,
                'quiet_zone': 1.5,
                'dpi': 300
            }
        )
        buffer.seek(0)
        return buffer.getvalue()
    except Exception as e:
        return None

if uploaded_csv and uploaded_pdf:
    try:
        if uploaded_csv.name.endswith(".csv"):
            try:
                df = pd.read_csv(uploaded_csv, dtype=str)
            except UnicodeDecodeError:
                uploaded_csv.seek(0)
                df = pd.read_csv(uploaded_csv, encoding="latin1", dtype=str)
        else:
            df = pd.read_excel(uploaded_csv, dtype=str)
    except Exception as e:
        st.error(f"File read karne me error: {e}")
        st.stop()

    # Column Auto-Detection
    col_mapping = {str(col).strip().lower(): col for col in df.columns}
    order_col = next((col_mapping[c] for c in col_mapping if "order" in c), None)
    msku_col = next((col_mapping[c] for c in col_mapping if "sku" in c or "msku" in c), None)
    tracking_col = next((col_mapping[c] for c in col_mapping if "track" in c or "tracing" in c), None)

    st.success(f"Matched Columns: Order = **{order_col}** | SKU = **{msku_col}** | Tracking = **{tracking_col}**")

    if not (order_col and msku_col and tracking_col):
        st.error("CSV me Order ID, SKU aur Tracking ID column nahi mila!")
        st.stop()

    # Records build karna
    shipment_records = []
    for _, row in df[[order_col, msku_col, tracking_col]].dropna().iterrows():
        raw_oid = clean_val(row[order_col])
        clean_oid = clean_alphanumeric(raw_oid)
        sku_val = clean_val(row[msku_col])
        track_val = clean_val(row[tracking_col])
        if clean_oid and track_val:
            shipment_records.append({
                "order_clean": clean_oid,
                "sku_val": sku_val,
                "sku_clean": clean_alphanumeric(sku_val),
                "track": track_val
            })

    st.info(f"Total Records in CSV: **{len(shipment_records)}**")

    if st.button("🚀 Process & Stamp Invoices Now", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()

        pdf_bytes = uploaded_pdf.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        new_doc = fitz.open()

        total_pages = len(doc)
        matched_count = 0
        removed_pan_pages = 0

        for page_num in range(total_pages):
            progress = (page_num + 1) / total_pages
            progress_bar.progress(progress)
            status_text.text(f"Processing Page {page_num + 1} of {total_pages}...")

            page = doc[page_num]
            raw_text = page.get_text()
            text_lower = raw_text.lower()
            text_clean = clean_alphanumeric(raw_text)

            # Rule 1: PAN Check - AALCR5906L na hone par page drop karo
            if TARGET_PAN not in text_lower:
                removed_pan_pages += 1
                continue

            # Multi-layer Order ID finder
            order_clean = None
            # Standard Amazon Order format: 3 digits - 7 digits - 7 digits
            order_match = re.search(r'(\d{3})\s*[-–—]\s*(\d{7})\s*[-–—]\s*(\d{7})', raw_text)
            if order_match:
                order_clean = f"{order_match.group(1)}{order_match.group(2)}{order_match.group(3)}"
            else:
                # Fallback: Order Number text ke aas-paas dhoondo
                num_match = re.search(r'order\s*number\s*[:\s]*(\d{3}[-–—\d]{14,16}\d)', raw_text, re.IGNORECASE)
                if num_match:
                    order_clean = clean_alphanumeric(num_match.group(1))

            target_tracking_id = None

            if order_clean:
                # Is order ke matching CSV records nikaalo
                matching_rows = [r for r in shipment_records if r["order_clean"] == order_clean]

                if matching_rows:
                    # Priority 1: SKU Match (Invoice text me SKU dhoondo)
                    for r in matching_rows:
                        if r["sku_clean"] and r["sku_clean"] in text_clean:
                            target_tracking_id = r["track"]
                            break

                    # Priority 2: Fallback (Agar single row ho ya text format alag ho)
                    if not target_tracking_id:
                        target_tracking_id = matching_rows[0]["track"]

            # Rule 2: Barcode aur Tracking Stamping
            if target_tracking_id:
                barcode_rect = fitz.Rect(40, 58, 235, 82)

                # Background box
                page.draw_rect(
                    barcode_rect,
                    color=(1.0, 1.0, 1.0),
                    fill=(1.0, 1.0, 1.0),
                    width=0
                )

                barcode_img_bytes = generate_barcode_image(target_tracking_id)
                if barcode_img_bytes:
                    page.insert_image(barcode_rect, stream=barcode_img_bytes, keep_proportion=False)

                # A. Barcode ke theek neeche BOLD Tracking ID
                page.insert_text(
                    (barcode_rect.x0 + 10, 95),
                    f"TRACKING: {target_tracking_id}",
                    fontsize=10.5,
                    fontname="hebo",
                    color=(0, 0, 0)
                )

                # B. Order Date ke theek neeche BOLD Tracking ID
                date_instances = page.search_for("Order Date:")
                if not date_instances:
                    date_instances = page.search_for("Order Date")

                if date_instances:
                    first_date_rect = date_instances[0]
                    page.insert_text(
                        (first_date_rect.x0, first_date_rect.y1 + 13),
                        f"Tracking ID: {target_tracking_id}",
                        fontsize=9.5,
                        fontname="hebo",
                        color=(0, 0, 0)
                    )

                matched_count += 1

            # PAN match wale sabhi pages PDF me save honge
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

        output_buffer = io.BytesIO()
        new_doc.save(output_buffer)
        output_buffer.seek(0)

        status_text.empty()
        progress_bar.empty()

        st.balloons()
        st.success(
            f"🎉 **Processing Complete!**\n\n"
            f"- Total Pages Kept: **{len(new_doc)}**\n"
            f"- Barcode Stamped: **{matched_count}** pages\n"
            f"- Non-PAN Pages Filtered: **{removed_pan_pages}** pages"
        )

        st.download_button(
            label="📥 Download Filtered Barcode PDF",
            data=output_buffer,
            file_name=f"Filtered_Stamped_{uploaded_pdf.name}",
            mime="application/pdf"
        )
