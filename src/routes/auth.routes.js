const express = require('express');
const jwt = require('jsonwebtoken');
const User = require('../models/User');
const auth = require('../middleware/auth');

const router = express.Router();

function generateTokens(userId) {
  const accessToken = jwt.sign(
    { userId },
    process.env.JWT_SECRET,
    { expiresIn: process.env.JWT_EXPIRES_IN || '7d' }
  );
  const refreshToken = jwt.sign(
    { userId, type: 'refresh' },
    process.env.JWT_SECRET,
    { expiresIn: process.env.JWT_REFRESH_EXPIRES_IN || '30d' }
  );
  return { accessToken, refreshToken };
}

router.post('/register', async (req, res) => {
  try {
    const { email, password, full_name } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    const existingUser = await User.findOne({ email: email.toLowerCase() });
    if (existingUser) {
      return res.status(409).json({ error: 'Email already registered' });
    }

    const user = new User({
      email: email.toLowerCase(),
      password,
      fullName: full_name || ''
    });
    await user.save();

    const tokens = generateTokens(user._id);
    user.refreshTokens.push({ token: tokens.refreshToken });
    await user.save();

    res.status(201).json({
      access_token: tokens.accessToken,
      refresh_token: tokens.refreshToken,
      token_type: 'Bearer',
      expires_in: 604800,
      user: {
        id: user._id.toString(),
        email: user.email,
        full_name: user.fullName,
        is_premium: user.isPremium,
        premium_until: user.premiumUntil,
        conversion_count: user.conversionCount,
        daily_conversion_count: user.dailyConversionCount,
        created_at: user.createdAt,
        email_verified: user.emailVerified
      }
    });
  } catch (error) {
    console.error('Register error:', error);
    res.status(500).json({ error: 'Registration failed' });
  }
});

router.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    const user = await User.findOne({ email: email.toLowerCase() });
    if (!user) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const isMatch = await user.comparePassword(password);
    if (!isMatch) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const tokens = generateTokens(user._id);
    user.refreshTokens.push({ token: tokens.refreshToken });
    if (user.refreshTokens.length > 5) {
      user.refreshTokens = user.refreshTokens.slice(-5);
    }
    await user.save();

    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (!user.lastConversionDate || user.lastConversionDate < todayStart) {
      user.dailyConversionCount = 0;
    }
    user.lastConversionDate = now;
    await user.save();

    res.json({
      access_token: tokens.accessToken,
      refresh_token: tokens.refreshToken,
      token_type: 'Bearer',
      expires_in: 604800,
      user: {
        id: user._id.toString(),
        email: user.email,
        full_name: user.fullName,
        is_premium: user.isPremium,
        premium_until: user.premiumUntil,
        conversion_count: user.conversionCount,
        daily_conversion_count: user.dailyConversionCount,
        created_at: user.createdAt,
        email_verified: user.emailVerified
      }
    });
  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ error: 'Login failed' });
  }
});

router.post('/refresh', async (req, res) => {
  try {
    const { refresh_token } = req.body;
    if (!refresh_token) {
      return res.status(400).json({ error: 'Refresh token is required' });
    }

    let decoded;
    try {
      decoded = jwt.verify(refresh_token, process.env.JWT_SECRET);
    } catch (err) {
      return res.status(401).json({ error: 'Invalid or expired refresh token' });
    }

    const user = await User.findById(decoded.userId);
    if (!user) {
      return res.status(401).json({ error: 'User not found' });
    }

    const tokenExists = user.refreshTokens.some(t => t.token === refresh_token);
    if (!tokenExists) {
      return res.status(401).json({ error: 'Refresh token not recognized' });
    }

    user.refreshTokens = user.refreshTokens.filter(t => t.token !== refresh_token);

    const tokens = generateTokens(user._id);
    user.refreshTokens.push({ token: tokens.refreshToken });
    await user.save();

    res.json({
      access_token: tokens.accessToken,
      refresh_token: tokens.refreshToken,
      token_type: 'Bearer',
      expires_in: 604800
    });
  } catch (error) {
    console.error('Refresh error:', error);
    res.status(500).json({ error: 'Token refresh failed' });
  }
});

router.get('/me', auth, async (req, res) => {
  try {
    const user = req.user;
    res.json({
      id: user._id.toString(),
      email: user.email,
      full_name: user.fullName,
      is_premium: user.isPremium,
      premium_until: user.premiumUntil,
      conversion_count: user.conversionCount,
      daily_conversion_count: user.dailyConversionCount,
      created_at: user.createdAt,
      email_verified: user.emailVerified
    });
  } catch (error) {
    console.error('Profile error:', error);
    res.status(500).json({ error: 'Failed to get profile' });
  }
});

router.put('/me', auth, async (req, res) => {
  try {
    const { full_name } = req.body;
    const user = req.user;

    if (full_name !== undefined) {
      user.fullName = full_name;
    }
    await user.save();

    res.json({
      id: user._id.toString(),
      email: user.email,
      full_name: user.fullName,
      is_premium: user.isPremium,
      premium_until: user.premiumUntil,
      conversion_count: user.conversionCount,
      daily_conversion_count: user.dailyConversionCount,
      created_at: user.createdAt,
      email_verified: user.emailVerified
    });
  } catch (error) {
    console.error('Update profile error:', error);
    res.status(500).json({ error: 'Failed to update profile' });
  }
});

module.exports = router;
