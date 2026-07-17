import { jwtVerify } from "jose";
import { z } from "zod";
import {
  TokenPayload,
  TokenPayloadSchema,
  UserMeResponse,
  UserMeResponseSchema,
} from "../core/ApiSchemas";
import { GameEnv } from "../core/configuration/Config";
import { PersistentIdSchema } from "../core/Schemas";
import { ServerEnv } from "./ServerEnv";

type TokenVerificationResult =
  | {
      type: "success";
      persistentId: string;
      claims: TokenPayload | null;
    }
  | { type: "error"; message: string };

export async function verifyClientToken(
  token: string,
): Promise<TokenVerificationResult> {
  // Auth bypass: accept any token as a persistent ID
  return { type: "success", persistentId: token, claims: null };
}

export async function getUserMe(
  _token: string,
): Promise<
  | { type: "success"; response: UserMeResponse }
  | { type: "error"; message: string }
> {
  // Auth bypass: return a default user response
  return {
    type: "success",
    response: {
      user: {},
      player: {
        publicId: "default",
        adfree: false,
        unlimitedRanked: false,
        canCreatePublicLobbies: false,
        flares: [],
        achievements: { singleplayerMap: [] },
        friends: [],
        subscription: null,
      },
    },
  };
}
