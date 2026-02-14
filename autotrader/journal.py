#!/usr/bin/env python3
"""
journal.py — Trade Psychology Journal
Log emotional state, decisions, and lessons. Review patterns over time.

Usage:
    python journal.py              # View recent entries
    python journal.py --add        # Add new entry
    python journal.py --insights   # Show patterns & insights
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

JOURNAL_FILE = "logs/journal.csv"
FIELDS = ["date", "time", "mood", "confidence", "market_read", "trades_today",
          "followed_plan", "mistakes", "lessons", "notes"]


def add_entry():
    """Interactive journal entry."""
    print(f"\n{'='*60}")
    print(f"  TRADE JOURNAL — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
    }
    
    print("\n  Rate 1-10:")
    entry["mood"] = input("  Mood (calm=10, stressed=1): ").strip() or "5"
    entry["confidence"] = input("  Confidence in positions: ").strip() or "5"
    entry["market_read"] = input("  Market read accuracy: ").strip() or "5"
    
    entry["trades_today"] = input("\n  Trades executed today: ").strip() or "0"
    entry["followed_plan"] = input("  Followed the plan? (y/n): ").strip() or "y"
    entry["mistakes"] = input("  Mistakes made: ").strip() or "None"
    entry["lessons"] = input("  Key lesson: ").strip() or ""
    entry["notes"] = input("  Additional notes: ").strip() or ""
    
    os.makedirs("logs", exist_ok=True)
    if os.path.exists(JOURNAL_FILE):
        df = pd.read_csv(JOURNAL_FILE)
        df = pd.concat([df, pd.DataFrame([entry])], ignore_index=True)
    else:
        df = pd.DataFrame([entry])
    
    df.to_csv(JOURNAL_FILE, index=False)
    print(f"\n  ✅ Journal entry saved.")


def show_recent(n: int = 5):
    """Show recent journal entries."""
    if not os.path.exists(JOURNAL_FILE):
        print("  No journal entries yet. Run: python journal.py --add")
        return
    
    df = pd.read_csv(JOURNAL_FILE)
    print(f"\n{'='*60}")
    print(f"  JOURNAL — Recent Entries")
    print(f"{'='*60}")
    
    for _, row in df.tail(n).iterrows():
        print(f"\n  📅 {row['date']} {row.get('time', '')}")
        print(f"  Mood: {row.get('mood','?')}/10 | Confidence: {row.get('confidence','?')}/10 | "
              f"Market Read: {row.get('market_read','?')}/10")
        if row.get("followed_plan", "y") != "y":
            print(f"  ⚠️ Did NOT follow plan")
        if row.get("mistakes", "None") != "None":
            print(f"  Mistakes: {row['mistakes']}")
        if row.get("lessons"):
            print(f"  Lesson: {row['lessons']}")
        if row.get("notes"):
            print(f"  Notes: {row['notes']}")


def show_insights():
    """Analyze journal patterns."""
    if not os.path.exists(JOURNAL_FILE):
        print("  Need journal entries for insights.")
        return
    
    df = pd.read_csv(JOURNAL_FILE)
    if len(df) < 3:
        print("  Need at least 3 entries for insights.")
        show_recent()
        return
    
    print(f"\n{'='*60}")
    print(f"  JOURNAL INSIGHTS ({len(df)} entries)")
    print(f"{'='*60}")
    
    # Convert numeric fields
    for col in ["mood", "confidence", "market_read"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    print(f"\n  Averages:")
    print(f"  Mood:           {df['mood'].mean():.1f}/10")
    print(f"  Confidence:     {df['confidence'].mean():.1f}/10")
    print(f"  Market Read:    {df['market_read'].mean():.1f}/10")
    
    plan_follow = df[df["followed_plan"] == "y"]
    print(f"\n  Plan Adherence: {len(plan_follow)}/{len(df)} ({len(plan_follow)/len(df)*100:.0f}%)")
    
    # Common mistakes
    mistakes = df[df["mistakes"] != "None"]["mistakes"].dropna()
    if not mistakes.empty:
        print(f"\n  Common Mistakes:")
        for m in mistakes.tail(5):
            print(f"    • {m}")
    
    # Lessons
    lessons = df["lessons"].dropna()
    lessons = lessons[lessons != ""]
    if not lessons.empty:
        print(f"\n  Recent Lessons:")
        for l in lessons.tail(5):
            print(f"    💡 {l}")
    
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", action="store_true")
    parser.add_argument("--insights", action="store_true")
    parser.add_argument("--entries", type=int, default=5)
    args = parser.parse_args()
    
    if args.add:
        add_entry()
    elif args.insights:
        show_insights()
    else:
        show_recent(args.entries)


if __name__ == "__main__":
    main()
