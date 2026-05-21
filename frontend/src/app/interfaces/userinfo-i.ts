export interface UserInfoI {
    provider_id:string,
    email:string,
    name:string,
    role:string,
    id:string,
    is_active:boolean
}

export interface UserValidationI {
    is_valid:boolean,
    id:string | null,
    role:string | null,
    is_active:boolean | null,
}