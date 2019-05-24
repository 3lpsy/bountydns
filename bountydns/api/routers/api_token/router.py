from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from bountydns.core import logger, only
from bountydns.core.security import (
    ScopedTo,
    TokenPayload,
    create_bearer_token,
    current_user,
)
from bountydns.db.models.user import User
from bountydns.core.entities.api_token import (
    ApiTokensResponse,
    ApiTokenResponse,
    ApiTokenRepo,
    ApiTokenCreateForm,
    SensitiveApiTokenResponse,
    SensitiveApiTokenData,
)
from bountydns.core.entities.dns_server import DnsServerRepo

from bountydns.core.entities import SortQS, PaginationQS, BaseResponse


router = APIRouter()
options = {"prefix": ""}


@router.post("/api-token/sync", name="api_token.sync", response_model=ApiTokenResponse)
async def sync(
    api_token_repo: ApiTokenRepo = Depends(ApiTokenRepo),
    dns_server_repo: DnsServerRepo = Depends(DnsServerRepo),
    token: TokenPayload = Depends(ScopedTo("api-token:syncable")),
):
    scopes = token.scopes
    if "api-token" in scopes or "api-token:syncable" in scopes:
        api_token = None
        dns_server = None
        if not dns_server_repo.exists(name=token.payload.dns_server_name.lower()):
            dns_server_repo.clear()
            logger.info("saving dns server from api token")
            dns_server = dns_server_repo.create(
                dict(name=token.payload.dns_server_name.lower())
            ).results()
        else:
            dns_server = dns_server_repo.results()

        if not api_token_repo.loads("dns_server").exists(token=token.token):
            api_token_repo.clear()
            logger.info("saving api token from auth token")
            item = api_token_repo.create(
                dict(
                    token=token.token,
                    scopes=" ".join(scopes),
                    dns_server=dns_server,
                    expires_at=datetime.utcfromtimestamp(float(token.exp)),
                )
            ).data()
            api_token_id = item.id
            item = (
                api_token_repo.clear()
                .loads("dns_server")
                .get(api_token_id)
                .includes("dns_server")
                .data()
            )
        else:
            logger.info("token already exists in database")
            item = api_token_repo.loads("dns_server").includes("dns_server").data()
        return ApiTokenResponse(api_token=item)

    else:
        raise HTTPException(403, detail="Not found")


@router.get("/api-token", name="api_token.index", response_model=ApiTokensResponse)
async def index(
    sort_qs: SortQS = Depends(SortQS),
    pagination: PaginationQS = Depends(PaginationQS),
    api_token_repo: ApiTokenRepo = Depends(ApiTokenRepo),
    token: TokenPayload = Depends(ScopedTo("api-token:list")),
    includes: List[str] = Query(None),
):
    pg, items = (
        api_token_repo.loads("dns_server")
        .strict()
        .sort(sort_qs)
        .paginate(pagination)
        .includes(includes)
        .data()
    )
    return ApiTokensResponse(pagination=pg, api_tokens=items)


@router.post("/api-token", name="api_token.store", response_model=ApiTokenResponse)
async def store(
    form: ApiTokenCreateForm,
    api_token_repo: ApiTokenRepo = Depends(ApiTokenRepo),
    dns_server_repo: DnsServerRepo = Depends(DnsServerRepo),
    token: TokenPayload = Depends(ScopedTo("api-token:create")),
    user: User = Depends(current_user),
):
    dns_server = dns_server_repo.first_or_fail(id=form.dns_server_id).results()

    scopes = []
    for requested_scope in form.scopes.split(" "):
        request_scope_satisfied = False
        for user_token in token.scopes:
            # TODO: double check this, pretty lenient
            # if a:b in a:b:c
            if user_token in requested_scope:
                request_scope_satisfied = True
        if not request_scope_satisfied:
            logger.warning(f"Attempt to create unauthorized scope {requested_scope}")
            raise HTTPException(403, detail="unauthorized")
        else:
            scopes.append(requested_scope)

    # TODO: use better randomness

    token = create_bearer_token(
        data={
            "sub": user.id,
            "scopes": " ".join(scopes),
            "dns_server_name": dns_server.name,
        }
    )

    data = {
        "scopes": " ".join(scopes),
        "token": str(token.decode()),
        "expires_at": form.expires_at,
        "dns_server_id": form.dns_server_id,
    }

    api_token = api_token_repo.create(data).data()
    return ApiTokenResponse(api_token=api_token)


@router.get(
    "/api-token/{api_token_id}", name="api_token.show", response_model=ApiTokenResponse
)
async def show(
    api_token_id: int,
    api_token_repo: ApiTokenRepo = Depends(ApiTokenRepo),
    token: TokenPayload = Depends(ScopedTo("api-token:read")),
    includes: List[str] = Query(None),
):
    if (
        not api_token_repo.loads("dns_server")
        .strict()
        .includes(includes)
        .exists(api_token_id)
    ):
        raise HTTPException(404, detail="Not found")
    api_token = api_token_repo.data()
    return ApiTokenResponse(api_token=api_token)


@router.get(
    "/api-token/{api_token_id}/sensitive",
    name="api_token.show.sensitive",
    response_model=SensitiveApiTokenResponse,
)
async def sensitive(
    api_token_id: int,
    api_token_repo: ApiTokenRepo = Depends(ApiTokenRepo),
    token: TokenPayload = Depends(ScopedTo("api-token:read")),
    includes: List[str] = Query(None),
):
    # TODO: require stronger scope
    if not api_token_repo.exists(api_token_id):
        raise HTTPException(404, detail="Not found")
    api_token = (
        api_token_repo.loads("dns_server")
        .set_data_model(SensitiveApiTokenData)
        .includes(includes)
        .data()
    )
    return SensitiveApiTokenResponse(api_token=api_token)


@router.delete("/api-token/{api_token_id}", response_model=BaseResponse)
async def destroy(
    api_token_id: int,
    api_token_repo: ApiTokenRepo = Depends(ApiTokenRepo),
    token: TokenPayload = Depends(ScopedTo("api-token:destroy")),
):
    messages = [{"text": "Deactivation Succesful", "type": "success"}]
    if not api_token_repo.exists(api_token_id):
        return BaseResponse(messages=messages)
    api_token_repo.deactivate(api_token_id)
    return BaseResponse(messages=messages)
