import rqdatac as rq


def init_rq():
    """Initialize RiceQuant connection."""
    rq.init(
        "tcp://license:"
        "iJTkO29NlrZ23X6M5w29Gh_4gShTv46OvOdm9EFZQfKnMg58DCKQBnSV0eay4MoG0ZhzhX_LTms"
        "00WMswme83iOk4ag7Z0OzToI04B67QbOWpicDqD7qxcd7TmK6bAKCTHBz-6wuGI7Zdrp9Z9Iop5BSH"
        "GqYvAm-nXJ-SsCHfoA=dcrc05HTqctrrjbxZjLDlYqv08eY68tPZGYfO_3PosCUVmbfw4WbyLzS6n9BG5"
        "EbP4ZCZ5r89rHrOHYfxY5fL5zOA3SfxO7oDdd3mHhgwPIlGNOKGkQvJhx637sQ2697R-qZThciVWKVD01dD"
        "70rCBuhHAIit26fGOhluTipHGQ=@rqdatad-pro.ricequant.com:16011"
    )
