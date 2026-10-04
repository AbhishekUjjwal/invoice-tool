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
st.write("Shipment Report aur Invoice PDF upload karein. **Strict PAN + Exact Multi-SKU Tracking Match** apply hoga.")

TARGET_PAN = "aalcr5906l"

uploaded_csv = st.file_uploader("1. Upload Shipment Report (CSV / Excel)", type=["csv", "xlsx", "xls"])
uploaded_pdf = st.file_uploader("2. Upload Invoice PDF", type=["pdf"])

def clean_val(v):
    if pd.isna(v):
        return ""
    s = str(v).strip()
    s = re.sub(r'^[="\']+|["\']+$', '', s)
    return s.strip()

def clean_alphanumeric(text):
    """Bina space, bina symbol ke lowercase text banata hai"""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()

def generate_barcode_image(code_text):
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
        st.error(f"File read error: {e}")
        st.stop()

    col_mapping = {str(col).strip().lower(): col for col in df.columns}
    order_col = next((col_mapping[c] for c in col_mapping if "order" in c), None)
    msku_col = next((col_mapping[c] for c in col_mapping if "sku" in c or "msku" in c), None)
    tracking_col = next((col_mapping[c] for c in col_mapping if "track" in c or "tracing" in c), None)

    st.success(f"Matched Columns: Order = **{order_col}** | SKU = **{msku_col}** | Tracking = **{tracking_col}**")

    if not (order_col and msku_col and tracking_col):
        st.error("CSV me required columns nahi mile!")
        st.stop()

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

    if st.button("🚀 Process & Stamp Invoices", type="primary"):
        pdf_bytes = uploaded_pdf.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        new_doc = fitz.open()

        total_pages = len(doc)
        matched_count = 0
        removed_pan_pages = 0

        for page_num in range(total_pages):
            page = doc[page_num]
            raw_text = page.get_text()
            text_lower = raw_text.lower()
            text_clean = clean_alphanumeric(raw_text)

            # Rule 1: Strict PAN Check
            if TARGET_PAN not in text_lower:
                removed_pan_pages += 1
                continue

            # Extract 17-digit Order Number
            order_clean = None
            order_match = re.search(r'(\d{3})\s*[-–—]\s*(\d{7})\s*[-–—]\s*(\d{7})', raw_text)
            if order_match:
                order_clean = f"{order_match.group(1)}{order_match.group(2)}{order_match.group(3)}"
            else:
                num_match = re.search(r'order\s*number\s*[:\s]*(\d{3}[-–—\d]{14,16}\d)', raw_text, re.IGNORECASE)
                if num_match:
                    order_clean = clean_alphanumeric(num_match.group(1))

            target_tracking_id = None

            if order_clean:
                # Find all records for this order in CSV
                matching_rows = [r for r in shipment_records if r["order_clean"] == order_clean]

                if len(matching_rows) == 1:
                    target_tracking_id = matching_rows[0]["track"]
                elif len(matching_rows) > 1:
                    # 1. Bracket extraction: Amazon writes ( SKU ) in description
                    brackets = re.findall(r'\(\s*([^()]+?)\s*\)', raw_text)
                    cleaned_bracket_items = [clean_alphanumeric(b) for b in brackets]

                    # Match SKU from brackets
                    for r in matching_rows:
                        if r["sku_clean"] in cleaned_bracket_items:
                            target_tracking_id = r["track"]
                            break

                    # 2. Match SKU anywhere in normalized text
                    if not target_tracking_id:
                        for r in matching_rows:
                            if r["sku_clean"] and r["sku_clean"] in text_clean:
                                target_tracking_id = r["track"]
                                break

                    # 3. Partial / word boundary match (e.g. ORDMUPL120 or A-ORBNEGM100TG)
                    if not target_tracking_id:
                        for r in matching_rows:
                            core_sku = re.sub(r'^[a-zA-Z]-', '', r["sku_clean"]) # strip leading prefix like a-
                            if len(core_sku) >= 4 and core_sku in text_clean:
                                target_tracking_id = r["track"]
                                break

                    # 4. Fallback if still not matched
                    if not target_tracking_id:
                        target_tracking_id = matching_rows[0]["track"]

            # Rule 2: Barcode & Tracking Stamping
            if target_tracking_id:
                barcode_rect = fitz.Rect(40, 58, 235, 82)
                page.draw_rect(barcode_rect, color=(1.0, 1.0, 1.0), fill=(1.0, 1.0, 1.0), width=0)

                barcode_img_bytes = generate_barcode_image(target_tracking_id)
                if barcode_img_bytes:
                    page.insert_image(barcode_rect, stream=barcode_img_bytes, keep_proportion=False)

                page.insert_text(
                    (barcode_rect.x0 + 10, 95),
                    f"TRACKING: {target_tracking_id}",
                    fontsize=10.5,
                    fontname="hebo",
                    color=(0, 0, 0)
                )

                date_instances = page.search_for("Order Date:") or page.search_for("Order Date")
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

            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

        output_buffer = io.BytesIO()
        new_doc.save(output_buffer)
        output_buffer.seek(0)

        st.balloons()
        st.success(
            f"🎉 **Processing Complete!**\n\n"
            f"- Total Pages Kept: **{len(new_doc)}**\n"
            f"- Barcode Stamped: **{matched_count}** pages\n"
            f"- Non-PAN Removed: **{removed_pan_pages}** pages"
        )

        st.download_button(
            label="📥 Download Filtered Barcode PDF",
            data=output_buffer,
            file_name=f"Filtered_Stamped_{uploaded_pdf.name}",
            mime="application/pdf"
        )
