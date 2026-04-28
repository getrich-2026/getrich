-- ============================================================
-- 访问控制函数
-- ============================================================
-- can_access_content：判断某个用户能否访问某条内容（策略正文 / 信号 / 文章）
--
-- 判定顺序（任一满足即可访问）：
--   1. 内容本身公开（access_tier = 0）
--   2. 延迟免费已到期（published + delay_free_hours < now）
--   3. 用户当前会员 tier >= access_tier
--   4. 策略场景下：存在有效的 PayG 授权 strategy_access_grants
--   5. 策略场景下：存在有效的周期订阅 user_strategy_subscriptions
-- ============================================================

CREATE OR REPLACE FUNCTION frontend.can_access_content(
    p_user_id     UUID,
    p_access_tier SMALLINT,
    p_delay_free  INT,
    p_published   TIMESTAMPTZ,
    p_strategy_id UUID DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_user_tier SMALLINT := 0;
BEGIN
    -- 1. 公开内容
    IF p_access_tier = 0 THEN
        RETURN TRUE;
    END IF;

    -- 2. 延迟免费到期
    IF p_delay_free IS NOT NULL
       AND p_published IS NOT NULL
       AND p_published + (p_delay_free || ' hours')::INTERVAL < NOW()
    THEN
        RETURN TRUE;
    END IF;

    -- 匿名用户（未登录）到这里还没过 = 不能访问
    IF p_user_id IS NULL THEN
        RETURN FALSE;
    END IF;

    -- 3. 用户当前最高 tier
    SELECT mp.level INTO v_user_tier
    FROM frontend.user_memberships um
    JOIN frontend.membership_plans mp ON mp.id = um.plan_id
    WHERE um.user_id = p_user_id
      AND um.status = 'active'
      AND um.expires_at > NOW()
    ORDER BY mp.level DESC
    LIMIT 1;

    IF COALESCE(v_user_tier, 0) >= p_access_tier THEN
        RETURN TRUE;
    END IF;

    -- 4. PayG 授权（仅策略相关内容）
    IF p_strategy_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM frontend.strategy_access_grants
        WHERE user_id = p_user_id
          AND strategy_id = p_strategy_id
          AND (expires_at IS NULL OR expires_at > NOW())
    ) THEN
        RETURN TRUE;
    END IF;

    -- 5. 周期订阅（仅策略相关内容）
    IF p_strategy_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM frontend.user_strategy_subscriptions
        WHERE user_id = p_user_id
          AND strategy_id = p_strategy_id
          AND status = 'active'
          AND expire_date >= CURRENT_DATE
    ) THEN
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================
-- can_access_strategies_bulk：批量版本，用于策略列表页
-- 返回每个 strategy_id 对应的 accessible 布尔值
-- 用法：
--   SELECT s.*, a.accessible
--   FROM frontend.strategies s
--   JOIN frontend.can_access_strategies_bulk($1, ARRAY(SELECT id FROM frontend.strategies WHERE ...)) a
--        ON a.strategy_id = s.id
-- ============================================================

CREATE OR REPLACE FUNCTION frontend.can_access_strategies_bulk(
    p_user_id      UUID,
    p_strategy_ids UUID[]
) RETURNS TABLE (strategy_id UUID, accessible BOOLEAN) AS $$
    SELECT
        s.id,
        frontend.can_access_content(
            p_user_id,
            s.access_tier,
            NULL::INT,              -- 策略正文不走 delay_free
            s.published_at,
            s.id
        )
    FROM frontend.strategies s
    WHERE s.id = ANY(p_strategy_ids);
$$ LANGUAGE sql STABLE;
