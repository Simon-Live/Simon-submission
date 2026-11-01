"""TICKET-114: the people step offers only tracks that move (cherry-picked from the team e6d65a7, serverless-modal)."""



def test_people_offered_only_when_they_move():
    """A track whose box stays put (a poster, a reflection) is not offered; one that moves is, and is picked
    automatically when it is the only one. A clip where nothing moves keeps everyone."""
    from part7 import people

    def track(pid, boxes):
        return [{"frame": i, "people": [{"id": pid, "bbox": b, "confidence": 0.9}]} for i, b in enumerate(boxes)]

    n = 20
    person = [[200, 100 + (i % 5) * 20, 120, 380 - (i % 5) * 40] for i in range(n)]  # hinges: height and top move
    poster = [[550, 200, 54, 35 + (i % 2)] for i in range(n)]                          # 1 px of jitter
    frames = [{"frame": i, "people": track("0", person)[i]["people"] + track("1", poster)[i]["people"]} for i in range(n)]
    offered = people.summarize(frames, 640, 480)
    assert [p["id"] for p in offered] == ["0"] and offered[0]["motion"] >= people.MIN_MOTION
    assert people.auto_id(offered) == "0"
    still_only = [{"frame": i, "people": track("1", poster)[i]["people"]} for i in range(n)]
    assert [p["id"] for p in people.summarize(still_only, 640, 480)] == ["1"]
