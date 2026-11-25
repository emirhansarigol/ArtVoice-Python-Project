from pydantic import BaseModel, EmailStr

# 1. Frontend'den sadece email adresi bekliyoruz
class MagicLinkRequest(BaseModel):
    email: EmailStr

# 2. Linke tıklandığında frontend bize linkteki token'ı gönderecek
class VerifyTokenRequest(BaseModel):
    token: str

# 3. Süresi biten oturumu yenilemek için frontend bize elindeki uzun ömürlü token'ı gönderecek
class RefreshTokenRequest(BaseModel):
    refresh_token: str