from src.commamatrix.api import DialogOrigin


class VKWallCommentsContext(DialogOrigin):
    owner_id: int
    post_id: int


a = VKWallCommentsContext(owner_id=1, post_id=1)

print(a.context_key())
