import pandas as pd
from db.client import upsert

WEEKDAYS = ["월","화","수","목","금","토","일"]
TIMEBANDS = ["00~06","06~11","11~14","14~17","17~21","21~24"]
GENDERS = {"남성":"남", "여성":"여"}
AGES = ["10","20","30","40","50","60_이상"]

def to_quarter(code):
    s = str(code)
    return f"{s[:4]}Q{s[4]}"

def to_key(tb):
    return tb.replace("~", "-")

def load(csv_path, dong_names):
    df = pd.read_csv(csv_path, encoding="cp949")
    df = df[df["행정동_코드_명"].isin(dong_names)]

    rows = []
    for _, r in df.iterrows():
        total = r["당월_매출_금액"] or 1

        weekday_ratio = {d: round(r[f"{d}요일_매출_금액"] / total, 4) for d in WEEKDAYS}
        timeband_ratio = {to_key(t): round(r[f"시간대_{t}_매출_금액"] / total, 4) for t in TIMEBANDS}
        gender_ratio = {k: round(r[f"{g}_매출_금액"] / total, 4) for g, k in GENDERS.items()}
        age_ratio = {a: round(r[f"연령대_{a}_매출_금액"] / total, 4) for a in AGES}

        rows.append({
            "quarter": to_quarter(r["기준_년분기_코드"]),
            "dong_code": str(r["행정동_코드"]),
            "dong_name": r["행정동_코드_명"],
            "industry_code": str(r["서비스_업종_코드"]),
            "industry_name": r["서비스_업종_코드_명"],
            "sales_amount": int(r["당월_매출_금액"]),
            "sales_count": int(r["당월_매출_건수"]),
            "weekday_ratio": weekday_ratio,
            "timeband_ratio": timeband_ratio,
            "gender_ratio": gender_ratio,
            "age_ratio": age_ratio,
        })

    upsert("sales_profile", rows, on_conflict="quarter,dong_code,industry_code")
    print(f"{len(rows)}건 적재 완료")
    return rows

if __name__ == "__main__":
    load("data/raw/sales_profile_2025.csv", dong_names=["자양3동"])