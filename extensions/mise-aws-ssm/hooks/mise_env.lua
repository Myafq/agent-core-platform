local cmd = require("cmd")

local function shell_quote(value)
    return "'" .. value:gsub("'", "'\\\"'\\\"'") .. "'"
end

local function required_string(options, key)
    local value = options[key]
    if type(value) ~= "string" or value == "" then
        error(key .. " must be a non-empty string")
    end
    return value
end

local function valid_environment_key(key)
    return type(key) == "string" and key:match("^[A-Za-z_][A-Za-z0-9_]*$") ~= nil
end

function PLUGIN:MiseEnv(ctx)
    local options = ctx.options or {}
    local parameters = options.parameters
    if type(parameters) ~= "table" or next(parameters) == nil then
        error("parameters must map environment-variable names to SSM parameter names")
    end

    local aws_env = {}
    if options.profile ~= nil then
        aws_env.AWS_PROFILE = required_string(options, "profile")
    end
    if options.region ~= nil then
        aws_env.AWS_REGION = required_string(options, "region")
    end

    local keys = {}
    for key, _ in pairs(parameters) do
        if not valid_environment_key(key) then
            error("invalid environment-variable name: " .. tostring(key))
        end
        table.insert(keys, key)
    end
    table.sort(keys)

    local result = {}
    for _, key in ipairs(keys) do
        local parameter_name = parameters[key]
        if type(parameter_name) ~= "string" or parameter_name == "" then
            error("parameter name for " .. key .. " must be a non-empty string")
        end

        local value = cmd.exec(
            "aws ssm get-parameter --name " .. shell_quote(parameter_name)
                .. " --with-decryption --query " .. shell_quote("Parameter.Value")
                .. " --output text",
            {env = aws_env}
        ):gsub("[\r\n]+$", "")

        table.insert(result, {key = key, value = value})
    end

    return result
end
