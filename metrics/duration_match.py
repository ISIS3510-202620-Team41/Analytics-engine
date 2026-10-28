"""BQ7: Determine the frequency and proportion with which joined activities fit strictly within the user's
available free time (Type 2)"""

from filters import Filters, build_where


def fetch_activity_selections(conn, f: Filters) -> list:
    """
    Retrieves recommended activity selections to analyze if they fit within 
    the user's available free time, ordered chronologically.
    """
    where, params = build_where(conn, f, ("recommended_activity_selected",))
    
    query = (
        f"SELECT user_id, activity_id, category, free_time_minutes, activity_duration_minutes, "
        f"occurred_at, received_at "
        f"FROM events "
        f"WHERE {where} "
        f"ORDER BY occurred_at, received_at, event_id"
    )
    
    return conn.execute(query, params).fetchall()


def duration_match(conn, f: Filters) -> dict:
    """
    Evaluates whether selected activities fit within the user's declared free time,
    providing both overall and category-level results.
    """
    rows = fetch_activity_selections(conn, f)
    
    seen_selections = set()
    matches = 0
    overflows = 0
    missing_values = 0
    
    # Dictionary to maintain separate match and overflow counters for each category
    category_stats = {}
    
    for row in rows:
        user_id = row["user_id"]
        activity_id = row["activity_id"]
        
        # Avoid counting duplicate user/activity selections
        selection_key = (user_id, activity_id)
        if selection_key in seen_selections:
            continue
        seen_selections.add(selection_key)
        
        free_time = row["free_time_minutes"]
        activity_duration = row["activity_duration_minutes"]
        category = row["category"]
        
        # Initialize category with three counters
        if category and category not in category_stats:
            category_stats[category] = {"matches": 0, "overflows": 0, "missing_values": 0}
        
        # Increment both overall and category missing counters
        if free_time is None or activity_duration is None:
            missing_values += 1
            if category:
                category_stats[category]["missing_values"] += 1
            continue
            
        # Compare activity_duration_minutes <= free_time_minutes
        if activity_duration <= free_time:
            matches += 1
            if category:
                category_stats[category]["matches"] += 1
        else:
            overflows += 1
            if category:
                category_stats[category]["overflows"] += 1
                
    valid_selections = matches + overflows
    total_selections = len(seen_selections)
    
    if valid_selections > 0:
        match_rate = matches / valid_selections
        overflow_rate = overflows / valid_selections
    else:
        match_rate = 0.0
        overflow_rate = 0.0
        
    if total_selections > 0:
        missing_rate = missing_values / total_selections
    else:
        missing_rate = 0.0
        
    # Calculate category-level rates for Streamlit
    categories_result = {}
    for cat, stats in category_stats.items():
        cat_matches = stats["matches"]
        cat_overflows = stats["overflows"]
        cat_missing = stats["missing_values"]
        cat_valid = cat_matches + cat_overflows
        cat_total = cat_valid + cat_missing
        
        if cat_valid > 0:
            cat_match_rate = cat_matches / cat_valid
            cat_overflow_rate = cat_overflows / cat_valid
        else:
            cat_match_rate = 0.0
            cat_overflow_rate = 0.0
            
        if cat_total > 0:
            cat_missing_rate = cat_missing / cat_total
        else:
            cat_missing_rate = 0.0
            
        # Include missing counter in final category result
        categories_result[cat] = {
            "matches": cat_matches,
            "overflows": cat_overflows,
            "missingValues": cat_missing,
            "validSelections": cat_valid,
            "matchRate": cat_match_rate,
            "overflowRate": cat_overflow_rate,
            "missingRate": cat_missing_rate,
        }
            
    return {
        "matches": matches,
        "overflows": overflows,
        "missingValues": missing_values,
        "totalUniqueSelections": total_selections,
        "validSelections": valid_selections,
        "matchRate": match_rate,
        "overflowRate": overflow_rate,
        "missingRate": missing_rate,
        "categories": categories_result,
    }